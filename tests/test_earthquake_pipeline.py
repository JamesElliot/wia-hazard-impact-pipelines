import json
import urllib.error
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from rasterio.transform import from_origin
from shapely.geometry import box

from conftest import make_worldpop_tif
from wia_pipelines.config import RunConfig
from wia_pipelines.core.admin import build_admin_aoi
from wia_pipelines.core.assets import shared_cache_root, url_cache_key
from wia_pipelines.hazards.earthquake.client import build_catalog_url
from wia_pipelines.hazards.earthquake.pipeline import (
    RunInputs,
    _fetch_with_retry,
    run_pipeline,
    validate_inputs,
)


def _admin_gdf() -> gpd.GeoDataFrame:
    # Lowercase column names, matching real COD-AB files (default.yml's field
    # config is uppercase, but that's resolved case-insensitively against
    # whatever the file actually has -- see hazards/_admin_config.py). Some
    # downstream code (visualize.write_run_maps's merge key) assumes the
    # resolved pcode column is lowercase, which only holds for real data;
    # matching that convention here keeps this fixture representative of a
    # real run rather than exercising an unrelated, pre-existing case-only
    # edge case.
    return gpd.GeoDataFrame(
        {
            "iso3": ["TST", "TST"],
            "adm0_pcode": ["TST", "TST"],
            "adm1_pcode": ["TST1", "TST1"],
            "adm2_pcode": ["TST101", "TST102"],
            "adm2_en": ["West", "East"],
            "adm2_ref": ["West", "East"],
        },
        geometry=[box(-1, 0, 0, 1), box(0, 0, 1, 1)],
        crs=4326,
    )


def _inputs(tmp_path: Path, *, worldpop_shape=(10, 20), worldpop_transform=None) -> RunInputs:
    admin_path = tmp_path / "admin.gpkg"
    _admin_gdf().to_file(admin_path, driver="GPKG")
    population_path = make_worldpop_tif(
        tmp_path / "population.tif",
        shape=worldpop_shape,
        value=1.0,
        nodata=-9999,
        transform=worldpop_transform or from_origin(-1, 1, 0.1, 0.1),
    )
    return RunInputs(
        iso3="TST",
        window_end="2025-12-31",
        worldpop=population_path,
        admin=admin_path,
        out=tmp_path / "outputs",
    )


def test_validate_inputs_reports_admin_and_population(tmp_path):
    result = validate_inputs(_inputs(tmp_path))
    assert result["window_start"] == "2025-01-01"
    assert result["window_end"] == "2025-12-31"
    assert result["admin_features"] == 2
    assert result["population"]["width"] == 20


def _seed_empty_catalog_cache(inputs: RunInputs) -> None:
    # run_pipeline derives the catalog URL deterministically from the AOI
    # bounds + window, exactly like this; pre-seeding download_cached's cache
    # path lets the pipeline run for real (including its own caching code
    # path) without needing live USGS network access or mocking.
    run = RunConfig(
        hazard="earthquake",
        iso3=inputs.iso3,
        as_of_date=inputs.window_end,
        lookback_months=int(inputs.lookback_months),
        output_root=inputs.out,
        target_adm_level=2,
        buffer_km=500.0,
    )
    admin = _admin_gdf().to_crs(4326)
    aoi = build_admin_aoi(admin, buffer_km=run.buffer_km)
    catalog_url = build_catalog_url(
        run.window_start.isoformat(), run.window_end.isoformat(), aoi["aoi_bounds"]
    )
    usgs_cache = shared_cache_root(inputs.out, "usgs")
    catalog_path = usgs_cache / "catalogues" / f"{url_cache_key(catalog_url)}.geojson"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")


def test_run_pipeline_full_worldpop_coverage_assigns_all_population(tmp_path):
    # WorldPop raster spans exactly [-1, 1] x [0, 1], the same extent as the
    # two admin polygons combined -- assigned_fraction should be ~1.0, well
    # within the default 2% max_unassigned_fraction tolerance (METHOD-001).
    inputs = _inputs(tmp_path)
    _seed_empty_catalog_cache(inputs)
    run_dir = run_pipeline(inputs)
    metadata = json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8"))
    summary = metadata["country_summary"]
    assert summary["population_assigned_fraction"] == pytest.approx(1.0, abs=1e-6)
    assert summary["population_raster_total"] == pytest.approx(200.0, abs=1e-6)
    assert summary["pop_total"] == pytest.approx(200.0, abs=1e-6)


def test_run_pipeline_raises_when_unassigned_population_exceeds_tolerance(tmp_path):
    # WorldPop raster is widened to [-2, 2] (double the admin polygons'
    # combined [-1, 1] extent) -- half the raster's population now sits
    # outside every admin polygon, far past the default 2% tolerance.
    inputs = _inputs(tmp_path, worldpop_shape=(10, 40), worldpop_transform=from_origin(-2, 1, 0.1, 0.1))
    _seed_empty_catalog_cache(inputs)
    with pytest.raises(RuntimeError, match="WorldPop/admin denominator mismatch"):
        run_pipeline(inputs)


def test_fetch_with_retry_returns_first_success_without_retrying(monkeypatch):
    calls = []

    def fn():
        calls.append(1)
        return "ok"

    sleeps = []
    monkeypatch.setattr("wia_pipelines.hazards.earthquake.pipeline.time.sleep", sleeps.append)
    assert _fetch_with_retry(fn) == "ok"
    assert len(calls) == 1
    assert sleeps == []


def test_fetch_with_retry_recovers_after_transient_failures(monkeypatch):
    attempts = {"count": 0}

    def fn():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TimeoutError("simulated transient timeout")
        return "ok"

    sleeps = []
    monkeypatch.setattr("wia_pipelines.hazards.earthquake.pipeline.time.sleep", sleeps.append)
    assert _fetch_with_retry(fn) == "ok"
    assert attempts["count"] == 3
    assert len(sleeps) == 2  # backoff before attempts 2 and 3, none after the final success


def test_fetch_with_retry_reraises_after_exhausting_attempts(monkeypatch):
    def fn():
        raise urllib.error.URLError("simulated permanent failure")

    monkeypatch.setattr("wia_pipelines.hazards.earthquake.pipeline.time.sleep", lambda seconds: None)
    with pytest.raises(urllib.error.URLError, match="simulated permanent failure"):
        _fetch_with_retry(fn)


def test_fetch_with_retry_does_not_retry_non_transport_errors(monkeypatch):
    calls = []

    def fn():
        calls.append(1)
        raise ValueError("malformed response, retrying would not help")

    sleeps = []
    monkeypatch.setattr("wia_pipelines.hazards.earthquake.pipeline.time.sleep", sleeps.append)
    with pytest.raises(ValueError, match="malformed response"):
        _fetch_with_retry(fn)
    assert len(calls) == 1
    assert sleeps == []


def _seed_catalog_with_events(inputs: RunInputs, features: list[dict]) -> None:
    run = RunConfig(
        hazard="earthquake",
        iso3=inputs.iso3,
        as_of_date=inputs.window_end,
        lookback_months=int(inputs.lookback_months),
        output_root=inputs.out,
        target_adm_level=2,
        buffer_km=500.0,
    )
    admin = _admin_gdf().to_crs(4326)
    aoi = build_admin_aoi(admin, buffer_km=run.buffer_km)
    catalog_url = build_catalog_url(
        run.window_start.isoformat(), run.window_end.isoformat(), aoi["aoi_bounds"]
    )
    usgs_cache = shared_cache_root(inputs.out, "usgs")
    catalog_path = usgs_cache / "catalogues" / f"{url_cache_key(catalog_url)}.geojson"
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")


def _seed_detail_and_grid(inputs: RunInputs, event_id: str, detail_url: str, grid_url: str) -> None:
    usgs_cache = shared_cache_root(inputs.out, "usgs")
    detail = {
        "properties": {
            "products": {
                "shakemap": [
                    {
                        "preferredWeight": 1,
                        "updateTime": 1,
                        "status": "UPDATE",
                        "contents": {"download/grid.xml": {"url": grid_url}},
                    }
                ]
            }
        }
    }
    detail_path = usgs_cache / "events" / event_id / f"detail_{url_cache_key(detail_url)}.json"
    detail_path.parent.mkdir(parents=True, exist_ok=True)
    detail_path.write_text(json.dumps(detail), encoding="utf-8")

    grid_xml = b"""<shakemap_grid>
      <grid_specification lon_min="-0.5" lon_max="0.5" lat_min="0.25" lat_max="0.75"
        nominal_lon_spacing="1" nominal_lat_spacing="0.5" nlon="2" nlat="2"/>
      <grid_field index="1" name="LON"/><grid_field index="2" name="LAT"/>
      <grid_field index="3" name="MMI"/>
      <grid_data>-0.5 0.75 7.0 0.5 0.75 7.0 -0.5 0.25 7.0 0.5 0.25 7.0</grid_data>
    </shakemap_grid>"""
    grid_path = usgs_cache / "shakemaps" / f"{url_cache_key(grid_url)}.xml"
    grid_path.parent.mkdir(parents=True, exist_ok=True)
    grid_path.write_bytes(grid_xml)


def test_run_pipeline_preserves_catalog_order_across_concurrent_fetches(tmp_path):
    # Three events in a deliberately mixed order: excluded (scenario),
    # included (real earthquake with a valid shakemap), excluded (no
    # shakemap type reference). event_rows must come back in exactly this
    # catalog order regardless of the concurrent detail/grid fetch phases
    # (PERF-010) -- order is fixed by the upfront sequential pass, not by
    # fetch completion order.
    inputs = _inputs(tmp_path)
    features = [
        {
            "id": "scenario1",
            "properties": {
                "type": "earthquake",
                "time": 1,
                "title": "M 7.0 Scenario",
                "mag": 7.0,
                "magType": "mw",
                "types": ",shakemap,",
                "detail": "https://example.test/scenario1.json",
            },
            "geometry": {"type": "Point", "coordinates": [0.0, 0.5, 10.0]},
        },
        {
            "id": "real1",
            "properties": {
                "type": "earthquake",
                "time": 2,
                "title": "M 7.0 Toy",
                "mag": 7.0,
                "magType": "mw",
                "types": ",shakemap,",
                "detail": "https://example.test/real1.json",
            },
            "geometry": {"type": "Point", "coordinates": [0.0, 0.5, 10.0]},
        },
        {
            "id": "noshakemap1",
            "properties": {
                "type": "earthquake",
                "time": 3,
                "title": "M 4.0 Minor",
                "mag": 4.0,
                "magType": "mw",
                "types": ",origin,",
                "detail": "https://example.test/noshakemap1.json",
            },
            "geometry": {"type": "Point", "coordinates": [0.0, 0.5, 10.0]},
        },
    ]
    _seed_catalog_with_events(inputs, features)
    _seed_detail_and_grid(
        inputs, "real1", "https://example.test/real1.json", "https://example.test/real1_grid.xml"
    )
    run_dir = run_pipeline(inputs)
    event_path = next((run_dir / "qc").glob("*_events_*.csv"))
    events = pd.read_csv(event_path)
    assert list(events["event_id"]) == ["scenario1", "real1", "noshakemap1"]
    assert list(events["status"]) == ["excluded", "included", "excluded"]
    assert events.loc[events["event_id"] == "scenario1", "exclusion_reason"].iloc[0] == "scenario_or_test"
    assert (
        events.loc[events["event_id"] == "noshakemap1", "exclusion_reason"].iloc[0]
        == "no_catalog_shakemap_reference"
    )

    table = pd.read_csv(next((run_dir / "tables").glob("*.csv")))
    assert table["pop_total"].sum() == pytest.approx(200.0, abs=1e-6)
    assert table["pop_affected"].sum() == pytest.approx(200.0, abs=1e-6)  # MMI 7 everywhere >= threshold 6.0


def test_run_pipeline_all_touched_does_not_double_count_shared_boundary_pixels(tmp_path):
    # PERF-006: with admin.all_touched=true, the two admin polygons share a
    # boundary at x=0. rasterize-once must assign each boundary pixel to
    # exactly one polygon, so the per-admin totals must not sum to more than
    # the full raster total (the pre-refactor per-polygon geometry_mask loop
    # could double-count shared-boundary pixels under all_touched=true).
    config_path = tmp_path / "all_touched.yml"
    config_path.write_text("admin:\n  all_touched: true\n", encoding="utf-8")
    inputs = RunInputs(**{**_inputs(tmp_path).__dict__, "config": config_path})
    _seed_empty_catalog_cache(inputs)
    run_dir = run_pipeline(inputs)
    (table_path,) = (run_dir / "tables").glob("*.csv")
    table = pd.read_csv(table_path)
    assert table["pop_total"].sum() == pytest.approx(200.0, abs=1e-6)
