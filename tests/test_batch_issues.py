from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from wia_pipelines.batch.issues import build_issue_report, write_issue_report


class BatchIssuesTests(unittest.TestCase):
    def test_build_issue_report_flags_missing_worldpop_and_preflight_fail(self) -> None:
        readiness = pd.DataFrame(
            [
                {
                    "task_id": 1,
                    "iso3": "YEM",
                    "as_of_date": "2025-12-31",
                    "lookback_months": 12,
                    "target_adm_level": 2,
                    "is_valid_manifest": True,
                    "manifest_errors": "",
                    "worldpop_exists": False,
                    "worldpop_path": "missing.tif",
                    "admin_layer_exists": True,
                    "admin_has_required_cols": True,
                    "admin_feature_count": 10,
                    "admin_layer": "admin2",
                    "acled_exists": True,
                    "readiness_ok_all": False,
                }
            ]
        )
        preflight = pd.DataFrame(
            [
                {
                    "task_id": 1,
                    "spei_preflight_status": "FAIL",
                    "utci_preflight_status": "PASS",
                    "flood_preflight_status": "WARN",
                    "violence_preflight_status": "PASS",
                    "preflight_issues": "spei_error:test",
                }
            ]
        )

        issues = build_issue_report(readiness, preflight)
        self.assertGreaterEqual(len(issues), 3)
        self.assertIn("missing_worldpop", set(issues["code"]))
        self.assertIn("spei_preflight_fail", set(issues["code"]))
        self.assertIn("flood_preflight_warn", set(issues["code"]))

    def test_write_issue_report_outputs_files(self) -> None:
        readiness = pd.DataFrame(
            [
                {
                    "task_id": 1,
                    "iso3": "YEM",
                    "as_of_date": "2025-12-31",
                    "lookback_months": 12,
                    "target_adm_level": 2,
                    "is_valid_manifest": True,
                    "manifest_errors": "",
                    "worldpop_exists": True,
                    "worldpop_path": "ok.tif",
                    "admin_layer_exists": True,
                    "admin_has_required_cols": True,
                    "admin_feature_count": 10,
                    "admin_layer": "admin2",
                    "acled_exists": True,
                    "readiness_ok_all": True,
                }
            ]
        )
        preflight = pd.DataFrame(
            [
                {
                    "task_id": 1,
                    "spei_preflight_status": "PASS",
                    "utci_preflight_status": "PASS",
                    "flood_preflight_status": "PASS",
                    "violence_preflight_status": "PASS",
                    "preflight_issues": "",
                }
            ]
        )

        with tempfile.TemporaryDirectory() as td:
            out = write_issue_report(readiness, preflight, Path(td))
            self.assertTrue(Path(out["issues_csv"]).exists())
            self.assertTrue(Path(out["issues_md"]).exists())
            self.assertTrue(Path(out["issues_summary_json"]).exists())


if __name__ == "__main__":
    unittest.main()
