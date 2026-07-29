from __future__ import annotations

import csv
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from wia_pipelines.hazards.flood_bulk import (
    FloodBulkRunOptions,
    build_flood_bulk_plan,
    calendar_year_windows,
    run_flood_bulk,
)


def _options(tmp_path: Path, start_year: int = 2021, end_year: int = 2025) -> FloodBulkRunOptions:
    admin = tmp_path / "admin.zip"
    worldpop = tmp_path / "ssd_pop.tif"
    admin.write_bytes(b"admin")
    worldpop.write_bytes(b"population")
    return FloodBulkRunOptions(
        iso3="ssd",
        start_year=start_year,
        end_year=end_year,
        output_root=tmp_path / "outputs",
        admin_path=admin,
        worldpop_path=worldpop,
    )


def test_calendar_year_windows_are_inclusive() -> None:
    assert calendar_year_windows(2021, 2023) == [
        (2021, "2021-01-01", "2021-12-31"),
        (2022, "2022-01-01", "2022-12-31"),
        (2023, "2023-01-01", "2023-12-31"),
    ]
    with pytest.raises(ValueError, match="start_year"):
        calendar_year_windows(2023, 2021)


def test_default_ssd_plan_has_five_annual_windows(tmp_path: Path) -> None:
    plan = build_flood_bulk_plan(_options(tmp_path))
    assert [row["year"] for row in plan] == [2021, 2022, 2023, 2024, 2025]
    assert all(row["status"] == "pending" for row in plan)
    assert plan[-1]["window_end"] == "2025-12-31"


def test_bulk_run_resumes_complete_year_and_runs_missing_year(tmp_path: Path) -> None:
    options = _options(tmp_path, start_year=2024, end_year=2025)
    existing_dir = options.output_root / "SSD" / "2024-12-31_m12" / "flood"
    existing_paths = [
        existing_dir / "rasters/flood/SSD_flood_days_2024-01-01_2024-12-31.tif",
        existing_dir / "rasters/flood/SSD_flood_any_2024-01-01_2024-12-31.tif",
        existing_dir / "tables/SSD_admin2_flood_exposure_2024-01-01_2024-12-31.csv",
    ]
    for path in existing_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"complete")
    (existing_dir / "run_metadata.json").write_text(
        json.dumps({"flood_pop_affected": {"pop_affected_sum": 12.0, "pop_affected_pct": 3.0}}),
        encoding="utf-8",
    )

    def fake_run(run_options):
        year = run_options.inputs.as_of_date[:4]
        run_dir = options.output_root / "SSD" / f"{year}-12-31_m12" / "flood"
        outputs = {
            "flood_days_tif": str(run_dir / f"rasters/flood/SSD_flood_days_{year}-01-01_{year}-12-31.tif"),
            "flood_mask_tif": str(run_dir / f"rasters/flood/SSD_flood_any_{year}-01-01_{year}-12-31.tif"),
            "admin_table": str(run_dir / f"tables/SSD_admin2_flood_exposure_{year}-01-01_{year}-12-31.csv"),
        }
        return {"run_dir": str(run_dir), "outputs": outputs}

    with patch("wia_pipelines.hazards.flood_bulk.run_flood_pipeline", side_effect=fake_run) as runner:
        summary = run_flood_bulk(options)

    assert runner.call_count == 1
    assert runner.call_args.args[0].inputs.as_of_date == "2025-12-31"
    with summary.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["status"] for row in rows] == ["success", "success"]
    assert [row["reused_existing"] for row in rows] == ["True", "False"]
