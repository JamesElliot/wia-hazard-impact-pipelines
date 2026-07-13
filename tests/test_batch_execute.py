from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from wia_pipelines.batch.execute import run_batch_execution


class BatchExecutionTests(unittest.TestCase):
    def _write_inputs(self, td: str) -> tuple[Path, Path]:
        readiness = pd.DataFrame(
            [
                {
                    "task_id": 1,
                    "iso3": "YEM",
                    "as_of_date": "2025-12-31",
                    "lookback_months": 12,
                    "target_adm_level": 2,
                    "is_valid_manifest": True,
                    "can_run_violence": True,
                    "can_run_spei": False,
                    "can_run_utci": False,
                    "can_run_flood": False,
                    "admin_layer": "admin2",
                    "worldpop_path": "/tmp/yem.tif",
                    "acled_path": "/tmp/acled_yem.csv",
                }
            ]
        )
        preflight = pd.DataFrame(
            [
                {
                    "task_id": 1,
                    "violence_preflight_status": "PASS",
                    "spei_preflight_status": "SKIP",
                    "utci_preflight_status": "SKIP",
                    "flood_preflight_status": "SKIP",
                }
            ]
        )
        r = Path(td) / "readiness.csv"
        p = Path(td) / "preflight.csv"
        readiness.to_csv(r, index=False)
        preflight.to_csv(p, index=False)
        return r, p

    def test_batch_execution_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            readiness, preflight = self._write_inputs(td)
            out = run_batch_execution(
                readiness=readiness,
                preflight=preflight,
                out_dir=Path(td) / "out",
                pipelines=["violence"],
                dry_run=True,
            )
            self.assertEqual(out["summary"]["n_dry_run"], 1)
            self.assertEqual(out["summary"]["n_failed"], 0)
            self.assertTrue(Path(out["status_json"]).exists())

    def test_batch_execution_retry_and_fail(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            readiness, preflight = self._write_inputs(td)
            out = run_batch_execution(
                readiness=readiness,
                preflight=preflight,
                out_dir=Path(td) / "out",
                pipelines=["violence"],
                command_templates={"violence": "false"},
                max_retries=2,
                heartbeat_seconds=1,
            )
            self.assertEqual(out["summary"]["n_failed"], 1)
            report = pd.read_csv(out["report_csv"])
            self.assertEqual(int(report.iloc[0]["attempts"]), 2)
            self.assertEqual(str(report.iloc[0]["status"]).upper(), "FAILED")

    def test_batch_execution_success(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            readiness, preflight = self._write_inputs(td)
            out = run_batch_execution(
                readiness=readiness,
                preflight=preflight,
                out_dir=Path(td) / "out",
                pipelines=["violence"],
                command_templates={"violence": "printf 'ok\\n'"},
                max_retries=1,
                heartbeat_seconds=1,
            )
            self.assertEqual(out["summary"]["n_success"], 1)
            report = pd.read_csv(out["report_csv"])
            self.assertEqual(str(report.iloc[0]["status"]).upper(), "SUCCESS")


if __name__ == "__main__":
    unittest.main()
