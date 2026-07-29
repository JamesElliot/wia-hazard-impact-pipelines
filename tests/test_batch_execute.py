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

    def test_resume_ignores_report_from_a_different_manifest(self) -> None:
        # task_id is a manifest-relative row index that resets to 1 for every
        # manifest. A leftover report from an earlier, unrelated manifest
        # (different country, different window) that happens to reuse
        # task_id=1 must not be mistaken for this run's own history.
        with tempfile.TemporaryDirectory() as td:
            readiness, preflight = self._write_inputs(td)
            out_dir = Path(td) / "out"
            out_dir.mkdir()
            stale_report = pd.DataFrame(
                [
                    {
                        "task_id": 1,
                        "iso3": "SDN",
                        "as_of_date": "2026-06-30",
                        "lookback_months": 12,
                        "target_adm_level": 2,
                        "pipeline": "violence",
                        "started_utc": "2020-01-01T00:00:00+00:00",
                        "ended_utc": "2020-01-01T00:00:00+00:00",
                        "duration_seconds": 0,
                        "attempts": 0,
                        "status": "DRY_RUN",
                        "exit_code": None,
                        "log_path": "",
                        "error": "",
                        "command": "",
                    }
                ]
            )
            stale_report.to_csv(out_dir / "batch_run_report.csv", index=False)

            out = run_batch_execution(
                readiness=readiness,
                preflight=preflight,
                out_dir=out_dir,
                pipelines=["violence"],
                command_templates={"violence": "printf 'ok\\n'"},
                max_retries=1,
                heartbeat_seconds=1,
                resume=True,
            )
            self.assertEqual(out["summary"]["n_success"], 1)
            report = pd.read_csv(out["report_csv"])
            self.assertEqual(len(report), 1)
            self.assertEqual(str(report.iloc[0]["iso3"]), "YEM")
            self.assertEqual(str(report.iloc[0]["status"]).upper(), "SUCCESS")

    def test_resume_reruns_a_success_step_with_missing_run_metadata(self) -> None:
        # PERF-011: a prior SUCCESS row alone must not be trusted on resume --
        # if the run's own run_metadata.json is missing (e.g. truncated/
        # deleted/corrupted after the run reported success), the step must
        # be re-executed rather than silently skipped.
        with tempfile.TemporaryDirectory() as td:
            readiness, preflight = self._write_inputs(td)
            out_dir = Path(td) / "out"
            out_dir.mkdir()
            output_root = Path(td) / "data_out"
            stale_report = pd.DataFrame(
                [
                    {
                        "task_id": 1,
                        "iso3": "YEM",
                        "as_of_date": "2025-12-31",
                        "lookback_months": 12,
                        "target_adm_level": 2,
                        "pipeline": "violence",
                        "started_utc": "2020-01-01T00:00:00+00:00",
                        "ended_utc": "2020-01-01T00:00:00+00:00",
                        "duration_seconds": 0,
                        "attempts": 0,  # a real SUCCESS row would never have 0 attempts
                        "status": "SUCCESS",
                        "exit_code": 0,
                        "log_path": "",
                        "error": "",
                        "command": "",
                    }
                ]
            )
            stale_report.to_csv(out_dir / "batch_run_report.csv", index=False)
            self.assertFalse((output_root / "YEM").exists())

            out = run_batch_execution(
                readiness=readiness,
                preflight=preflight,
                out_dir=out_dir,
                output_root=output_root,
                pipelines=["violence"],
                command_templates={"violence": "printf 'ok\\n'"},
                max_retries=1,
                heartbeat_seconds=1,
                resume=True,
            )
            self.assertEqual(out["summary"]["n_success"], 1)
            report = pd.read_csv(out["report_csv"])
            self.assertEqual(len(report), 1)
            # attempts >= 1 proves this step was actually re-executed, not
            # silently carried forward from the stale (attempts=0) report row.
            self.assertGreaterEqual(int(report.iloc[0]["attempts"]), 1)

    def test_resume_skips_a_success_step_with_valid_run_metadata(self) -> None:
        # Counterpart to the above: a genuinely valid prior SUCCESS run
        # (real run_metadata.json on disk, schema-valid) must still be
        # trusted and skipped on resume -- PERF-011 only tightens the
        # invalid case, it must not make resume always re-run everything.
        with tempfile.TemporaryDirectory() as td:
            readiness, preflight = self._write_inputs(td)
            out_dir = Path(td) / "out"
            out_dir.mkdir()
            output_root = Path(td) / "data_out"

            from wia_pipelines.config import RunConfig
            from wia_pipelines.core.pipeline import build_hazard_run_context

            config = RunConfig(
                hazard="violence",
                iso3="YEM",
                as_of_date="2025-12-31",
                lookback_months=12,
                output_root=output_root,
            )
            ctx = build_hazard_run_context(config, create_dirs=True, write_metadata=True)
            self.assertTrue((ctx["layout"]["base"] / "run_metadata.json").exists())

            stale_report = pd.DataFrame(
                [
                    {
                        "task_id": 1,
                        "iso3": "YEM",
                        "as_of_date": "2025-12-31",
                        "lookback_months": 12,
                        "target_adm_level": 2,
                        "pipeline": "violence",
                        "started_utc": "2020-01-01T00:00:00+00:00",
                        "ended_utc": "2020-01-01T00:00:00+00:00",
                        "duration_seconds": 5,
                        "attempts": 1,
                        "status": "SUCCESS",
                        "exit_code": 0,
                        "log_path": "",
                        "error": "",
                        "command": "",
                    }
                ]
            )
            stale_report.to_csv(out_dir / "batch_run_report.csv", index=False)

            out = run_batch_execution(
                readiness=readiness,
                preflight=preflight,
                out_dir=out_dir,
                output_root=output_root,
                pipelines=["violence"],
                # If this ran for real, n_success would still be 1, so the
                # real assertion is `attempts` staying at the stale value
                # (proving no subprocess ran) -- point at a command that
                # would fail loudly if it were ever actually invoked.
                command_templates={"violence": "false"},
                max_retries=1,
                heartbeat_seconds=1,
                resume=True,
            )
            self.assertEqual(out["summary"]["n_success"], 1)
            report = pd.read_csv(out["report_csv"])
            self.assertEqual(len(report), 1)
            self.assertEqual(int(report.iloc[0]["attempts"]), 1)

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
