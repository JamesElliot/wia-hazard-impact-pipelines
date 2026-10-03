from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from wia_pipelines.batch.execute import (
    PIPELINES,
    _PIPELINE_HAZARD_DIR,
    _is_pipeline_eligible,
    hazard_config_arg,
    run_batch_execution,
)


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

    def test_utci_cold_is_a_default_batch_pipeline_sharing_utci_eligibility(self) -> None:
        self.assertIn("utci_cold", PIPELINES)
        self.assertEqual(_PIPELINE_HAZARD_DIR["utci_cold"], "cold")
        with tempfile.TemporaryDirectory() as td:
            readiness, preflight = self._write_inputs(td)
            r = pd.read_csv(readiness)
            r["can_run_utci"] = True
            r.to_csv(readiness, index=False)
            p = pd.read_csv(preflight)
            p["utci_preflight_status"] = "PASS"
            p.to_csv(preflight, index=False)
            out = run_batch_execution(
                readiness=readiness,
                preflight=preflight,
                out_dir=Path(td) / "out",
                pipelines=["utci", "utci_cold"],
                dry_run=True,
            )
            rows = out["rows"].set_index("pipeline")
            self.assertEqual(rows.loc["utci_cold", "status"], "DRY_RUN")
            self.assertIn("--extreme cold", rows.loc["utci_cold", "command"])
            self.assertNotIn("--extreme", rows.loc["utci", "command"])

    def test_utci_cold_skipped_when_utci_not_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            readiness, preflight = self._write_inputs(td)  # can_run_utci False, preflight SKIP
            out = run_batch_execution(
                readiness=readiness,
                preflight=preflight,
                out_dir=Path(td) / "out",
                pipelines=["utci_cold"],
                dry_run=True,
            )
            self.assertEqual(out["summary"]["n_skipped"], 1)
            self.assertEqual(out["rows"].iloc[0]["error"], "can_run_utci_false")

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


class EarthquakeCycloneBatchTests(unittest.TestCase):
    def _reports(self, td: str, **readiness_extra) -> tuple[Path, Path]:
        row = {
            "task_id": 1,
            "iso3": "MDG",
            "as_of_date": "2025-12-31",
            "lookback_months": 12,
            "target_adm_level": 2,
            "is_valid_manifest": True,
            "admin_layer": "admin2",
            "admin_layer_exists": True,
            "admin_has_required_cols": True,
            "worldpop_exists": True,
            "worldpop_path": "/tmp/mdg.tif",
        }
        row.update(readiness_extra)
        r, p = Path(td) / "r.csv", Path(td) / "p.csv"
        pd.DataFrame([row]).to_csv(r, index=False)
        # An older preflight report: no earthquake/cyclone columns.
        pd.DataFrame([{"task_id": 1, "violence_preflight_status": "PASS"}]).to_csv(p, index=False)
        return r, p

    def test_pipelines_include_earthquake_and_cyclone(self) -> None:
        self.assertIn("earthquake", PIPELINES)
        self.assertIn("cyclone", PIPELINES)

    def test_dry_run_uses_per_country_admin_layer_and_config(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            r, p = self._reports(td)
            override = Path(td) / "mdg" / "admin_boundaries.gpkg"
            with mock.patch(
                "wia_pipelines.batch.execute.resolve_admin_path", return_value=override
            ) as resolve:
                out = run_batch_execution(
                    readiness=r,
                    preflight=p,
                    out_dir=Path(td) / "out",
                    pipelines=["earthquake", "cyclone"],
                    dry_run=True,
                )
            self.assertEqual(out["summary"]["n_dry_run"], 2)
            resolve.assert_called()
            self.assertIsNone(resolve.call_args.args[0] if resolve.call_args.args else None)
            for cmd in out["rows"]["command"]:
                self.assertIn(f"--admin-path {override}", cmd)
                self.assertIn("--admin-layer admin2", cmd)
                self.assertIn("scripts/run_", cmd)

    def test_explicit_batch_admin_path_wins(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            r, p = self._reports(td)
            explicit = Path(td) / "custom.gpkg"
            out = run_batch_execution(
                readiness=r,
                preflight=p,
                out_dir=Path(td) / "out",
                pipelines=["earthquake"],
                admin_path=explicit,
                dry_run=True,
            )
            self.assertIn(f"--admin-path {explicit.resolve()}", out["rows"].iloc[0]["command"])

    def test_hazard_config_arg_applies_only_when_mapping_and_file_exist(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertEqual(hazard_config_arg("MDG", 2, root=root), "")
            (root / "configs").mkdir()
            (root / "configs" / "mdg_admin2_fields.yml").write_text("admin: {}\n", encoding="utf-8")
            self.assertEqual(
                hazard_config_arg("mdg", 2, root=root),
                f"--config {root / 'configs' / 'mdg_admin2_fields.yml'}",
            )
            self.assertEqual(hazard_config_arg("KEN", 2, root=root), "")
            self.assertEqual(hazard_config_arg("MDG", 3, root=root), "")

    def test_eligibility_uses_common_inputs_when_columns_absent(self) -> None:
        ok = pd.Series(
            {
                "is_valid_manifest": True,
                "admin_layer_exists": True,
                "admin_has_required_cols": True,
                "worldpop_exists": True,
            }
        )
        for pipeline in ("earthquake", "cyclone"):
            self.assertEqual(_is_pipeline_eligible(ok, pipeline), (True, "eligible"))
            missing = ok.copy()
            missing["worldpop_exists"] = False
            self.assertEqual(_is_pipeline_eligible(missing, pipeline), (False, f"can_run_{pipeline}_false"))

    def test_explicit_readiness_column_and_failed_preflight_are_respected(self) -> None:
        row = pd.Series({"is_valid_manifest": True, "can_run_cyclone": False})
        self.assertEqual(_is_pipeline_eligible(row, "cyclone"), (False, "can_run_cyclone_false"))
        row = pd.Series(
            {"is_valid_manifest": True, "can_run_cyclone": True, "cyclone_preflight_status": "FAIL"}
        )
        self.assertEqual(_is_pipeline_eligible(row, "cyclone"), (False, "cyclone_preflight_status_fail"))


if __name__ == "__main__":
    unittest.main()
