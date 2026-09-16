from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np
import xarray as xr

from wia_pipelines.hazards.spei import (
    SpeiPipelineRunOptions,
    SpeiRunInputs,
    _find_spei_var,
    _resolve_thresholds,
    build_spei_run_context,
    prepare_spei_geography,
    spei_month_window,
)

HAS_GEO = all(
    importlib.util.find_spec(m) is not None
    for m in ("geopandas", "rasterio", "shapely", "pyproj", "fiona", "numpy")
)


class SpeiWindowTests(unittest.TestCase):
    def test_month_window(self) -> None:
        window = spei_month_window("2025-12-31", lookback_months=3)
        self.assertEqual(window["months"], [(2025, 10), (2025, 11), (2025, 12)])
        self.assertEqual(window["start_yyyy_mm"], "2025-10")
        self.assertEqual(window["end_yyyy_mm"], "2025-12")

    def test_default_thresholds_match_documented_values(self) -> None:
        thresholds = _resolve_thresholds(None)
        self.assertEqual(
            thresholds,
            {"rel_spei_le_m1p0": -1.0, "rel_spei_le_m1p5": -1.5, "rel_spei_le_m2p0": -2.0},
        )

    def test_default_reporting_threshold_key_is_explicit(self) -> None:
        fields = SpeiPipelineRunOptions.__dataclass_fields__
        self.assertEqual(fields["default_threshold_key"].default, "rel_spei_le_m1p5")

    def test_build_run_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx = build_spei_run_context(
                SpeiRunInputs(
                    iso3="MLI",
                    as_of_date="2025-12-31",
                    output_root=Path(td) / "outputs",
                ),
                create_dirs=True,
                write_metadata=True,
            )
            self.assertTrue(ctx["layout"]["base"].exists())
            self.assertTrue(ctx["metadata_path"].exists())
            self.assertEqual(ctx["metadata"]["run_config"]["hazard"], "drought")
            self.assertEqual(ctx["layout"]["base"].name, "drought")
            self.assertEqual(ctx["layout"]["base"].parent.parent.name, "MLI")

    def test_find_spei_var_ignores_non_spatial_preferred_name(self) -> None:
        ds = xr.Dataset(
            data_vars={
                "SPEI3": xr.DataArray(np.array([0.0, 1.0]), dims=("bnds",)),
                "spei3_main": xr.DataArray(
                    np.zeros((1, 2, 3), dtype="float32"),
                    dims=("time", "lat", "lon"),
                ),
            }
        )
        self.assertEqual(_find_spei_var(ds), "spei3_main")


@unittest.skipUnless(HAS_GEO, "geospatial stack not installed")
class SpeiPipelineExecutionTests(unittest.TestCase):
    def test_run_spei_pipeline_golden_toy(self) -> None:
        # End-to-end run_spei_pipeline execution with no real CDS access:
        # download_cds is monkeypatched to synthesize a small SPEI3 NetCDF
        # covering the AOI instead of calling the live API. Every cell is
        # set below all three thresholds, so the whole admin unit should
        # read 100% affected -- a hand-computable golden case, mirroring
        # the pattern test_hazard_violence.py already uses.
        import zipfile
        from unittest.mock import patch

        import pandas as pd
        from rasterio.transform import from_origin
        from shapely.geometry import box

        import wia_pipelines.core.cds as core_cds
        import wia_pipelines.hazards.coverage_checks as coverage_checks
        from conftest import make_admin_gpkg, make_worldpop_tif
        from wia_pipelines.hazards.spei import SpeiPipelineRunOptions, run_spei_pipeline

        def fake_download_cds(dataset, request, out_zip):
            year = int(request["year"][0])
            month = int(request["month"][0])
            nc_path = out_zip.parent / f"{out_zip.stem}.nc"
            nc_path.parent.mkdir(parents=True, exist_ok=True)
            ds = xr.Dataset(
                {
                    "SPEI12": (
                        ("time", "lat", "lon"),
                        np.full((1, 7, 7), -2.0, dtype="float32"),
                    )
                },
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

            with (
                patch.object(core_cds, "download_cds", side_effect=fake_download_cds),
                patch.object(coverage_checks, "download_cds", side_effect=fake_download_cds),
            ):
                summary = run_spei_pipeline(
                    SpeiPipelineRunOptions(
                        inputs=self._spei_inputs(root),
                        admin_path=admin_path,
                        worldpop_path=worldpop_path,
                        admin_layer="admin2",
                        iso3_field="iso3",
                    )
                )

            table = pd.read_csv(summary["outputs"]["admin_table"])
            row = table.iloc[0]
            self.assertEqual(row["adm2_pcode"], "AAA001")
            self.assertAlmostEqual(row["population_total"], 1000.0, places=3)
            self.assertAlmostEqual(row["pct_affected"], 100.0, places=3)

            # DOC-006/PROD-003: WorldPop/admin inputs are checksummed for
            # reproducibility provenance.
            import hashlib
            import json as json_module

            metadata = json_module.loads(Path(summary["metadata_path"]).read_text(encoding="utf-8"))
            self.assertEqual(
                metadata["inputs"]["worldpop"]["sha256"],
                hashlib.sha256(worldpop_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(metadata["inputs"]["admin"]["path"], str(admin_path.resolve()))
            self.assertEqual(metadata["admin_source"]["vintage"], "TEST2026-01")
            self.assertIn("water_scarcity_spei12", str(summary["outputs"]["admin_table"]))

    def test_run_spei_pipeline_requests_accumulation_period_12(self) -> None:
        # Mechanism-verification for the SPEI3->SPEI12 method change: proves
        # the pipeline now requests/labels SPEI12 correctly. This cannot
        # assert a real population-affected delta from synthetic data -- see
        # the "Method change history" note in docs/methodology-alignment.md
        # for the documented pilot-country comparison that satisfies the
        # governance-required parity check.
        import zipfile
        from unittest.mock import patch

        from rasterio.transform import from_origin
        from shapely.geometry import box

        import wia_pipelines.core.cds as core_cds
        import wia_pipelines.hazards.coverage_checks as coverage_checks
        from conftest import make_admin_gpkg, make_worldpop_tif
        from wia_pipelines.hazards.spei import SpeiPipelineRunOptions, run_spei_pipeline

        captured_requests: list[dict] = []

        def fake_download_cds(dataset, request, out_zip):
            captured_requests.append(request)
            year = int(request["year"][0])
            month = int(request["month"][0])
            nc_path = out_zip.parent / f"{out_zip.stem}.nc"
            nc_path.parent.mkdir(parents=True, exist_ok=True)
            ds = xr.Dataset(
                {
                    "SPEI12": (
                        ("time", "lat", "lon"),
                        np.full((1, 7, 7), -2.0, dtype="float32"),
                    )
                },
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

            with (
                patch.object(core_cds, "download_cds", side_effect=fake_download_cds),
                patch.object(coverage_checks, "download_cds", side_effect=fake_download_cds),
            ):
                summary = run_spei_pipeline(
                    SpeiPipelineRunOptions(
                        inputs=self._spei_inputs(root),
                        admin_path=admin_path,
                        worldpop_path=worldpop_path,
                        admin_layer="admin2",
                        iso3_field="iso3",
                    )
                )

            self.assertTrue(captured_requests)
            for request in captured_requests:
                self.assertEqual(request["accumulation_period"], ["12"])

            import json as json_module

            metadata = json_module.loads(Path(summary["metadata_path"]).read_text(encoding="utf-8"))
            self.assertEqual(metadata["pipeline"], "water_scarcity_spei12")
            self.assertIn("water_scarcity_spei12", str(summary["outputs"]["admin_table"]))
            self.assertNotIn("water_scarcity_spei3_", str(summary["outputs"]["admin_table"]))

    def _run_with_sample_lat_range(self, lat_max: float):
        # Shrinks the fake CDS sample's spatial extent so its bounding box only
        # partially covers the admin AOI (box(0,0,1,1)), exercising the
        # two-tier preflight-coverage gate (ARCH-012) rather than the
        # full-coverage happy path the golden-toy test above covers.
        import json
        import zipfile
        from unittest.mock import patch

        from rasterio.transform import from_origin
        from shapely.geometry import box

        import wia_pipelines.core.cds as core_cds
        import wia_pipelines.hazards.coverage_checks as coverage_checks
        from conftest import make_admin_gpkg, make_worldpop_tif
        from wia_pipelines.hazards.spei import SpeiPipelineRunOptions, run_spei_pipeline

        def fake_download_cds(dataset, request, out_zip):
            year = int(request["year"][0])
            month = int(request["month"][0])
            nc_path = out_zip.parent / f"{out_zip.stem}.nc"
            nc_path.parent.mkdir(parents=True, exist_ok=True)
            ds = xr.Dataset(
                {"SPEI3": (("time", "lat", "lon"), np.full((1, 7, 7), -2.0, dtype="float32"))},
                coords={
                    "time": [np.datetime64(f"{year:04d}-{month:02d}-15")],
                    "lat": np.linspace(lat_max, -1.0, 7),
                    "lon": np.linspace(-1.0, 2.0, 7),
                },
            )
            ds.to_netcdf(nc_path)
            with zipfile.ZipFile(out_zip, "w") as zf:
                zf.write(nc_path, arcname=nc_path.name)
            return True, None

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
            options = SpeiPipelineRunOptions(
                inputs=self._spei_inputs(root),
                admin_path=admin_path,
                worldpop_path=worldpop_path,
                admin_layer="admin2",
                iso3_field="iso3",
            )
            with (
                patch.object(core_cds, "download_cds", side_effect=fake_download_cds),
                patch.object(coverage_checks, "download_cds", side_effect=fake_download_cds),
            ):
                summary = run_spei_pipeline(options)
            metadata = json.loads(Path(summary["metadata_path"]).read_text(encoding="utf-8"))
            return summary, metadata

    def test_sample_coverage_between_hard_min_and_target_warns_not_fails(self) -> None:
        # lat spans [-1, 0.75] -> overlap with admin's y-range [0, 1] is [0, 0.75],
        # i.e. 75% of the admin bbox area: above the 50% hard-min, below the 100% target.
        summary, metadata = self._run_with_sample_lat_range(lat_max=0.75)
        self.assertEqual(summary["status"], "SUCCESS")
        cov = metadata["preflight_coverage"]["spei_sample"]["coverage_pct"]
        self.assertAlmostEqual(cov, 75.0, places=3)
        messages = [w["message"] for w in metadata.get("warnings", [])]
        self.assertTrue(any("SPEI preflight coverage below target" in m for m in messages))

    def test_sample_coverage_below_hard_min_raises(self) -> None:
        # lat spans [-1, 0.4] -> overlap with [0, 1] is [0, 0.4] = 40% of the admin bbox,
        # below the 50% hard minimum, so this must still hard-fail.
        with self.assertRaises(RuntimeError):
            self._run_with_sample_lat_range(lat_max=0.4)

    @staticmethod
    def _spei_inputs(root: Path):
        from wia_pipelines.hazards.spei import SpeiRunInputs

        return SpeiRunInputs(
            iso3="AAA",
            as_of_date="2025-12-31",
            lookback_months=1,
            output_root=root / "outputs",
            target_adm_level=2,
        )


@unittest.skipUnless(HAS_GEO, "geospatial stack not installed")
class SpeiGeographyTests(unittest.TestCase):
    def test_prepare_spei_geography(self) -> None:
        from rasterio.transform import from_origin
        from shapely.geometry import box

        from conftest import make_admin_gpkg, make_worldpop_tif

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            gpkg = make_admin_gpkg(
                td_path / "admin.gpkg",
                geometries=[box(0, 0, 1, 1), box(1, 0, 2, 1), box(10, 10, 11, 11)],
                extra_columns={"iso3": ["AAA", "AAA", "BBB"], "adm_level": [2, 2, 2]},
                layer="admin2",
            )
            worldpop_tif = make_worldpop_tif(
                td_path / "wp.tif", shape=(4, 4), transform=from_origin(0, 2, 0.5, 0.5)
            )

            out = prepare_spei_geography(
                iso3="AAA",
                admin_path=gpkg,
                admin_layer="admin2",
                iso3_field="iso3",
                adm_level_field="adm_level",
                target_adm_level=2,
                worldpop_path=worldpop_tif,
            )
            self.assertIn("aoi", out)
            self.assertEqual(len(out["bounds_hash"]), 64)
            self.assertIsNotNone(out["overlap_report"])


if __name__ == "__main__":
    unittest.main()
