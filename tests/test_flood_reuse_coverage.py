from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from wia_pipelines.hazards.flood import (
    _reused_coverage_fields,
    flood_coverage_record_path,
    read_flood_coverage_record,
    write_flood_coverage_record,
)
from wia_pipelines.hazards.flood_parity import run_checks


def _build_run(run_dir: Path, flood_stac: dict) -> None:
    for sub in ("qc/flood", "rasters", "tables"):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    table_path = run_dir / "tables" / "table.csv"
    pd.DataFrame(
        {
            "adm2_pcode": ["A1", "A2"],
            "pop_total": [100.0, 200.0],
            "pop_affected_flood": [10.0, 20.0],
            "pct_affected_flood": [10.0, 10.0],
        }
    ).to_csv(table_path, index=False)
    days, mask, pop = (run_dir / "rasters" / n for n in ("days.tif", "mask.tif", "pop.tif"))
    for p in (days, mask, pop):
        p.write_bytes(b"placeholder")
    metadata = {
        "schema_version": "1.0.0",
        "run_id": run_dir.name,
        "created_utc": "2026-02-25T00:00:00+00:00",
        "run_config": {
            "hazard": "flood",
            "iso3": "MLI",
            "as_of_date": "2025-12-31",
            "lookback_months": 12,
            "window_start": "2025-01-01",
            "window_end": "2025-12-31",
            "target_adm_level": 2,
            "buffer_km": 0.0,
        },
        "paths": {
            "base": str(run_dir),
            "raw": str(run_dir / "raw"),
            "rasters": str(run_dir / "rasters"),
            "tables": str(run_dir / "tables"),
            "qc": str(run_dir / "qc"),
            "logs": str(run_dir / "logs"),
            "cache": str(run_dir / "_cache"),
        },
        "artifacts": [],
        "preflight_coverage": {
            "worldpop": {"coverage_pct": 99.9},
            "flood_stac": flood_stac,
            "thresholds": {
                "worldpop_coverage_min_pct": 98.0,
                "flood_stac_union_coverage_min_pct": 99.999,
            },
        },
        "admin2_flood_table": {"path": str(table_path)},
        "flood_mask": {"days_tif": str(days), "mask_tif": str(mask)},
        "flood_pop_affected": {"pop_tif": str(pop), "pop_affected_sum": 30.0},
    }
    (run_dir / "run_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")


def _flood_check(report: dict) -> dict:
    return next(c for c in report["checks"] if c["name"] == "preflight_flood_stac_threshold")


class CoverageRecordTests(unittest.TestCase):
    def test_round_trip_keeps_coverage_fields_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tif = Path(td) / "XXX_flood_days.tif"
            write_flood_coverage_record(
                tif,
                {
                    "union_bbox_coverage_pct": 87.9,
                    "union_full_coverage": False,
                    "union_above_hard_min": True,
                    "item_count": 4869,
                    "item_ids": ["a", "b"],
                },
            )
            rec = read_flood_coverage_record(tif)
            self.assertEqual(rec["union_bbox_coverage_pct"], 87.9)
            self.assertEqual(rec["item_count"], 4869)
            self.assertNotIn("item_ids", rec)
            self.assertTrue(flood_coverage_record_path(tif).name.endswith(".coverage.json"))

    def test_missing_or_corrupt_record_is_none(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tif = Path(td) / "XXX_flood_days.tif"
            self.assertIsNone(read_flood_coverage_record(tif))
            flood_coverage_record_path(tif).write_text("not json", encoding="utf-8")
            self.assertIsNone(read_flood_coverage_record(tif))

    def test_reused_fields_flag_whether_coverage_was_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tif = Path(td) / "XXX_flood_days.tif"
            self.assertEqual(_reused_coverage_fields(tif), {"coverage_recorded": False})
            write_flood_coverage_record(tif, {"union_bbox_coverage_pct": 73.1})
            fields = _reused_coverage_fields(tif)
            self.assertTrue(fields["coverage_recorded"])
            self.assertEqual(fields["union_bbox_coverage_pct"], 73.1)


class ParityReuseTests(unittest.TestCase):
    def test_reused_raster_without_recorded_coverage_warns_not_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "MLI_flood"
            _build_run(run_dir, {"reused_existing_flood_days": True, "coverage_recorded": False})
            report = run_checks(run_dir)
            self.assertEqual(_flood_check(report)["status"], "WARN")
            self.assertEqual(report["failures"], 0)

    def test_reused_raster_with_recorded_low_coverage_still_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "MLI_flood"
            _build_run(
                run_dir,
                {
                    "reused_existing_flood_days": True,
                    "coverage_recorded": True,
                    "union_bbox_coverage_pct": 87.9,
                },
            )
            report = run_checks(run_dir)
            self.assertEqual(_flood_check(report)["status"], "FAIL")

    def test_fresh_run_without_coverage_still_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "MLI_flood"
            _build_run(run_dir, {})
            report = run_checks(run_dir)
            self.assertEqual(_flood_check(report)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
