from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import xarray as xr
from rasterio.transform import from_origin
from shapely.geometry import box

from conftest import make_admin_gpkg, make_worldpop_tif
from wia_pipelines.batch.preflight import run_batch_preflight
from wia_pipelines.core.admin import admin_bounds_hash
from wia_pipelines.core.assets import shared_cache_root
from wia_pipelines.hazards.coverage_aoi import prepare_country_admin_context


def _fake_download_cds(dataset, request, out_zip):
    year = int(request["year"][0])
    month = int(request["month"][0])
    nc_path = out_zip.parent / f"{out_zip.stem}.nc"
    nc_path.parent.mkdir(parents=True, exist_ok=True)
    ds = xr.Dataset(
        {"SPEI3": (("time", "lat", "lon"), np.full((1, 7, 7), -2.0, dtype="float32"))},
        coords={
            "time": [np.datetime64(f"{year:04d}-{month:02d}-15")],
            "lat": np.linspace(2.0, -1.0, 7),
            "lon": np.linspace(-1.0, 2.0, 7),
        },
    )
    ds.to_netcdf(nc_path)
    with zipfile.ZipFile(out_zip, "w") as zf:
        zf.write(nc_path, arcname=nc_path.name)
    return True, None


def _readiness_row(iso3: str, worldpop_path: Path, task_id: int = 1) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "task_id": task_id,
                "iso3": iso3,
                "as_of_date": "2025-12-31",
                "lookback_months": 1,
                "target_adm_level": 2,
                "admin_layer": "admin2",
                "worldpop_path": str(worldpop_path),
                "can_run_spei": True,
                "can_run_utci": False,
                "can_run_flood": False,
                "can_run_violence": False,
            }
        ]
    )


def test_preflight_and_pipeline_compute_the_same_cds_bounds_hash(tmp_path: Path) -> None:
    # PERF-002's cross-cache-hit claim depends on this holding: preflight's
    # prepare_country_admin_context() and spei.py's own inline bounds/hash
    # computation must agree exactly for the same admin file/layer/buffer,
    # or a "shared" cache key would silently never actually hit.
    admin_path = make_admin_gpkg(
        tmp_path / "admin.gpkg",
        geometries=[box(0, 0, 1, 1)],
        extra_columns={"iso3": ["AAA"], "adm_level": [2], "adm2_pcode": ["AAA001"]},
        layer="admin2",
    )

    ctx = prepare_country_admin_context(
        iso3="AAA", admin_path=admin_path, admin_layer="admin2", iso3_field="iso3", cds_buffer_deg=0.25
    )
    preflight_hash = admin_bounds_hash("AAA", ctx["cds_bounds_wsen"])

    import geopandas as gpd
    from shapely.ops import unary_union

    from wia_pipelines.core.admin import filter_admin_for_iso3, load_admin_layer

    admin_all = load_admin_layer(admin_path, layer="admin2")
    admin_gdf = filter_admin_for_iso3(admin_all, iso3="AAA", iso3_field="iso3")
    admin_4326: gpd.GeoDataFrame = admin_gdf.to_crs("EPSG:4326")
    west, south, east, north = tuple(float(v) for v in unary_union(admin_4326.geometry).bounds)
    west_cds = max(-180.0, west - 0.25)
    south_cds = max(-90.0, south - 0.25)
    east_cds = min(180.0, east + 0.25)
    north_cds = min(90.0, north + 0.25)
    spei_side_hash = admin_bounds_hash("AAA", (west_cds, south_cds, east_cds, north_cds))

    assert preflight_hash == spei_side_hash


def test_preflight_spei_sample_is_cached_under_the_shared_location() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        admin_path = make_admin_gpkg(
            root / "admin.gpkg",
            geometries=[box(0, 0, 1, 1)],
            extra_columns={"iso3": ["AAA"], "adm_level": [2], "adm2_pcode": ["AAA001"]},
            layer="admin2",
        )
        worldpop_path = make_worldpop_tif(
            root / "worldpop.tif", shape=(10, 10), value=10.0, transform=from_origin(0, 1, 0.1, 0.1)
        )
        output_root = root / "outputs"
        readiness = _readiness_row("AAA", worldpop_path)

        import wia_pipelines.hazards.coverage_checks as coverage_checks

        with patch.object(coverage_checks, "download_cds", side_effect=_fake_download_cds):
            result = run_batch_preflight(
                readiness=readiness,
                admin_path=admin_path,
                sample_year=2025,
                sample_month=12,
                out_dir=root / "preflight_out",
                output_root=output_root,
            )

        assert result["report"].iloc[0]["spei_preflight_status"] in {"PASS", "WARN"}
        cache_dir = shared_cache_root(output_root, "cds_preflight_samples")
        cached = list(cache_dir.glob("AAA_spei_202512_*.zip"))
        assert len(cached) == 1


def test_pipeline_reuses_preflights_cds_sample_without_a_second_download() -> None:
    # End-to-end: run batch preflight first (populating the shared cache),
    # then run the real spei pipeline for the same country/window and
    # confirm the CDS download mock fires only once in total -- the
    # pipeline's own sample check must hit the cache preflight populated.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        admin_path = make_admin_gpkg(
            root / "admin.gpkg",
            geometries=[box(0, 0, 1, 1)],
            extra_columns={"iso3": ["AAA"], "adm_level": [2], "adm2_pcode": ["AAA001"]},
            layer="admin2",
        )
        worldpop_path = make_worldpop_tif(
            root / "worldpop.tif", shape=(10, 10), value=10.0, transform=from_origin(0, 1, 0.1, 0.1)
        )
        output_root = root / "outputs"
        readiness = _readiness_row("AAA", worldpop_path)

        import wia_pipelines.core.cds as core_cds
        import wia_pipelines.hazards.coverage_checks as coverage_checks

        # Step 1: batch preflight populates the shared sample cache.
        with patch.object(coverage_checks, "download_cds", side_effect=_fake_download_cds):
            run_batch_preflight(
                readiness=readiness,
                admin_path=admin_path,
                sample_year=2025,
                sample_month=12,
                out_dir=root / "preflight_out",
                output_root=output_root,
            )
        cache_dir = shared_cache_root(output_root, "cds_preflight_samples")
        (cached_zip,) = cache_dir.glob("AAA_spei_202512_*.zip")
        original_bytes = cached_zip.read_bytes()

        def sample_download_should_not_be_called(dataset, request, out_zip):
            raise AssertionError("SPEI sample was re-downloaded instead of reusing preflight's cache")

        from wia_pipelines.hazards.spei import SpeiPipelineRunOptions, SpeiRunInputs, run_spei_pipeline

        # Step 2: the real pipeline run. Its own sample check
        # (coverage_checks.download_cds) must reuse preflight's cached zip
        # rather than fetch again -- the mock below raises if that
        # assumption is wrong. The bulk month-download path
        # (core.cds.download_cds) is separate and unrelated to this
        # optimization, so it gets a normal working fake instead.
        with (
            patch.object(coverage_checks, "download_cds", side_effect=sample_download_should_not_be_called),
            patch.object(core_cds, "download_cds", side_effect=_fake_download_cds),
        ):
            summary = run_spei_pipeline(
                SpeiPipelineRunOptions(
                    inputs=SpeiRunInputs(
                        iso3="AAA",
                        as_of_date="2025-12-31",
                        lookback_months=1,
                        output_root=output_root,
                        target_adm_level=2,
                    ),
                    admin_path=admin_path,
                    worldpop_path=worldpop_path,
                    admin_layer="admin2",
                    iso3_field="iso3",
                )
            )

        assert summary["status"] == "SUCCESS"
        assert cached_zip.read_bytes() == original_bytes
