from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from wia_pipelines.hazards.cyclone.pipeline import RunInputs, run_pipeline


def _inputs(tmp_path: Path, *, complete=True, admin_level=2) -> RunInputs:
    admin = gpd.GeoDataFrame(
        {
            "ISO3": ["TST", "TST"],
            "ADM0_PCODE": ["TST", "TST"],
            "ADM1_PCODE": ["TST1", "TST1"],
            "ADM2_PCODE": ["TST101", "TST102"],
            "ADM2_EN": ["West", "East"],
            "ADM2_REF": ["West", "East"],
            "ADM3_PCODE": ["TST1011", "TST1021"],
            "ADM3_EN": ["West ward", "East ward"],
            "ADM3_REF": ["West ward", "East ward"],
        },
        geometry=[box(-1, 0, 0, 1), box(0, 0, 1, 1)],
        crs=4326,
    )
    admin_path = tmp_path / "admin.gpkg"
    admin.to_file(admin_path, driver="GPKG")

    population_path = tmp_path / "population.tif"
    profile = {
        "driver": "GTiff",
        "height": 10,
        "width": 20,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": from_origin(-1, 1, 0.1, 0.1),
        "nodata": -9999,
    }
    with rasterio.open(population_path, "w", **profile) as destination:
        destination.write(np.ones((10, 20), dtype="float32"), 1)

    rows = []
    for time, lon in (("2026-01-01 00:00:00", -0.55), ("2026-01-01 06:00:00", -0.45)):
        row = {
            "SID": "2026001N00000",
            "ISO_TIME": time,
            "LAT": 0.5,
            "LON": lon,
            "NAME": "TEST",
            "BASIN": "NA",
            "USA_WIND": 40,
        }
        for quadrant in ("NE", "SE", "SW", "NW"):
            row[f"USA_R34_{quadrant}"] = 20
        rows.append(row)
    if not complete:
        rows[1]["USA_R34_NW"] = None
    tracks_path = tmp_path / "ibtracs.csv"
    pd.DataFrame(rows).to_csv(tracks_path, index=False)
    config_path = None
    if admin_level == 3:
        config_path = tmp_path / "admin3.yml"
        config_path.write_text(
            "admin:\n"
            "  level: 3\n"
            "  fields:\n"
            "    adm3_pcode: ADM3_PCODE\n"
            "    adm3_name_en: ADM3_EN\n"
            "    adm3_name_local: ADM3_REF\n",
            encoding="utf-8",
        )
    return RunInputs(
        iso3="TST",
        window_end="2026-06-30",
        ibtracs=tracks_path,
        worldpop=population_path,
        admin=admin_path,
        out=tmp_path / "outputs",
        config=config_path,
    )


def test_pipeline_preserves_population_and_writes_auditable_outputs(tmp_path):
    output = run_pipeline(_inputs(tmp_path))
    table = pd.read_csv(output / "tables" / "HI06_TST_2026-06-30.csv")
    assert table["pop_total"].sum() == 200
    assert table.loc[table["adm2_pcode"] == "TST101", "pct_affected"].iloc[0] > 0
    assert table.loc[table["adm2_pcode"] == "TST102", "pct_affected"].iloc[0] == 0
    assert {
        "iso3",
        "admin_level",
        "admin_pcode",
        "period_start",
        "period_end",
        "hazard",
        "method_version",
        "population_total",
        "population_affected",
        "pct_affected",
    }.issubset(table.columns)
    assert (output / "rasters" / "HI06_TST_mask_2026-06-30.tif").exists()
    assert (output / "qc" / "HI06_TST_tracks_affected_population_2026-06-30.png").stat().st_size > 0
    assert (output / "qc" / "HI06_TST_pct_affected_admin2_2026-06-30.png").stat().st_size > 0
    assert (output / "run_metadata.json").exists()
    assert (output / "logs" / "HI06_TST.source.md").exists()


def test_pipeline_fails_when_primary_footprint_completeness_is_too_low(tmp_path):
    inputs = _inputs(tmp_path, complete=False)
    # One of two observations remains complete, which meets the 0.5 default.
    # Remove another quadrant from the remaining observation to force 0 completeness.
    frame = pd.read_csv(inputs.ibtracs)
    frame.loc[0, "USA_R34_NE"] = np.nan
    frame.to_csv(inputs.ibtracs, index=False)
    with pytest.raises(RuntimeError, match="No adequate primary footprint"):
        run_pipeline(inputs)


def test_no_storm_window_is_valid_zero_with_storm_audit_schema(tmp_path):
    inputs = _inputs(tmp_path)
    frame = pd.read_csv(inputs.ibtracs)
    frame["ISO_TIME"] = "2020-01-01 00:00:00"
    frame.to_csv(inputs.ibtracs, index=False)
    output = run_pipeline(inputs)
    table = pd.read_csv(output / "tables" / "HI06_TST_2026-06-30.csv")
    storms = pd.read_csv(output / "qc" / "HI06_TST_storms_2026-06-30.csv")
    assert table["pct_affected"].eq(0).all()
    assert storms.empty
    assert {"SID", "status", "radii_completeness_63"}.issubset(storms.columns)


def test_wrong_country_code_cannot_silently_process_all_admins(tmp_path):
    inputs = _inputs(tmp_path)
    wrong = RunInputs(**{**inputs.__dict__, "iso3": "XXX"})
    with pytest.raises(ValueError, match="No admin features match ISO3"):
        run_pipeline(wrong)


def test_pipeline_uses_configured_admin_level_in_results_and_map_name(tmp_path):
    output = run_pipeline(_inputs(tmp_path, admin_level=3))
    table = pd.read_csv(output / "tables" / "HI06_TST_2026-06-30.csv")
    assert {"adm2_pcode", "adm3_pcode", "adm3_name_en", "adm3_name_local"}.issubset(table.columns)
    assert "adm2_name_en" not in table.columns
    assert (output / "qc" / "HI06_TST_pct_affected_admin3_2026-06-30.png").exists()
