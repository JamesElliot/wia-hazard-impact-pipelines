from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from wia_pipelines.hazards.violence_parity import run_checks


class ViolenceParityTests(unittest.TestCase):
    def test_run_checks_passes_on_minimal_valid_run(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "YEM_2025-01-01_2025-12-31_m12_violence"
            (run_dir / "qc" / "violence").mkdir(parents=True, exist_ok=True)
            (run_dir / "results").mkdir(parents=True, exist_ok=True)

            table_path = run_dir / "results" / "adm2_stats.csv"
            pd.DataFrame(
                {
                    "adm2_pcode": ["A1", "A2"],
                    "pop_total": [100.0, 200.0],
                    "pop_affected": [10.0, 20.0],
                    "pct_affected": [10.0, 10.0],
                    "pop_weighted_event_count_sum": [40.0, 80.0],
                    "pop_weighted_mean_event_count": [0.4, 0.4],
                }
            ).to_csv(table_path, index=False)

            mask_tif = run_dir / "results" / "mask.tif"
            pop_tif = run_dir / "results" / "pop.tif"
            weighted_count_tif = run_dir / "results" / "pop_weighted_event_count.tif"
            count_tif = run_dir / "results" / "event_count.tif"
            mask_tif.write_bytes(b"x")
            pop_tif.write_bytes(b"x")
            weighted_count_tif.write_bytes(b"x")
            count_tif.write_bytes(b"x")

            metadata = {
                "schema_version": "1.0.0",
                "run_id": run_dir.name,
                "created_utc": "2026-02-25T00:00:00+00:00",
                "run_config": {
                    "hazard": "violence",
                    "iso3": "YEM",
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
                    "worldpop": {"coverage_pct": 100.0},
                    "thresholds": {"worldpop_coverage_min_pct": 98.0},
                    "acled_events": {"n_events_after_filters": 5},
                },
                "adm2_stats": {"adm2_stats_csv": str(table_path)},
                "hazard_mask": {
                    "mask_tif": str(mask_tif),
                    "threshold_metric": "event_count",
                    "threshold_value": 1,
                },
                "hazard_intensity": {"event_count_tif": str(count_tif)},
                "violence_config": {
                    "supported_event_types": ["Battles", "Riots", "Protests"],
                    "included_event_types": ["Battles", "Riots"],
                },
                "population_impact": {
                    "affected_pop_tif": str(pop_tif),
                    "affected_population": 30.0,
                    "pop_weighted_event_count_tif": str(weighted_count_tif),
                    "pop_weighted_mean_event_count": 0.4,
                },
            }
            (run_dir / "run_metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

            report = run_checks(run_dir)
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["failures"], 0)
            self.assertEqual(report["warnings"], 0)


if __name__ == "__main__":
    unittest.main()
