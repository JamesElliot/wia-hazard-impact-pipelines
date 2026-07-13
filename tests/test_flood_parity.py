from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from wia_pipelines.hazards.flood_parity import run_checks


class FloodParityTests(unittest.TestCase):
    def test_run_checks_passes_on_minimal_valid_run(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "MLI_2025-01-01_2025-12-31_m12_flood"
            (run_dir / "qc" / "flood").mkdir(parents=True, exist_ok=True)
            (run_dir / "rasters").mkdir(parents=True, exist_ok=True)
            (run_dir / "tables").mkdir(parents=True, exist_ok=True)

            table_path = run_dir / "tables" / "table.csv"
            pd.DataFrame(
                {
                    "adm2_pcode": ["A1", "A2"],
                    "pop_total": [100.0, 200.0],
                    "pop_affected_flood": [10.0, 20.0],
                    "pct_affected_flood": [10.0, 10.0],
                }
            ).to_csv(table_path, index=False)

            days = run_dir / "rasters" / "days.tif"
            mask = run_dir / "rasters" / "mask.tif"
            pop = run_dir / "rasters" / "pop.tif"
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
                    "flood_stac": {"union_bbox_coverage_pct": 100.0},
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

            report = run_checks(run_dir)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["failures"], 0)


if __name__ == "__main__":
    unittest.main()
