from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from wia_pipelines.cli import build_parser


class CliTests(unittest.TestCase):
    def test_run_cyclone_dry_run_executes(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run-cyclone",
                "--iso3",
                "MOZ",
                "--as-of-date",
                "2026-03-31",
                "--ibtracs-path",
                "data/cyclone/ibtracs.csv",
                "--worldpop-path",
                "data/population/moz.tif",
                "--admin-path",
                "data/cod-ab/moz.gpkg",
                "--dry-run",
            ]
        )
        self.assertEqual(args.func(args), 0)

    def test_init_run_command_executes(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "init-run",
                "--hazard",
                "flood",
                "--iso3",
                "MLI",
                "--as-of-date",
                "2025-12-31",
            ]
        )
        rc = args.func(args)
        self.assertEqual(rc, 0)

    def test_validate_metadata_command_logic(self) -> None:
        parser = build_parser()
        payload = {
            "schema_version": "1.0.0",
            "run_id": "MLI_2025-01-01_2025-12-31_m12_flood",
            "created_utc": "2026-02-24T00:00:00+00:00",
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
                "base": "outputs/flood/MLI/run",
                "raw": "outputs/flood/MLI/run/raw",
                "rasters": "outputs/flood/MLI/run/rasters",
                "tables": "outputs/flood/MLI/run/tables",
                "qc": "outputs/flood/MLI/run/qc",
                "logs": "outputs/flood/MLI/run/logs",
                "cache": "outputs/_cache/flood/MLI",
            },
            "artifacts": [],
        }
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "run_metadata.json"
            p.write_text(json.dumps(payload), encoding="utf-8")
            self.assertTrue(p.exists())
            args = parser.parse_args(
                [
                    "validate-metadata",
                    "--metadata",
                    str(p),
                ]
            )
            rc = args.func(args)
            self.assertEqual(rc, 0)

    def test_flood_postrun_skip_parity_executes(self) -> None:
        parser = build_parser()
        payload = {
            "schema_version": "1.0.0",
            "run_id": "MLI_2025-01-01_2025-12-31_m12_flood",
            "created_utc": "2026-02-24T00:00:00+00:00",
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
                "base": "outputs/flood/MLI/run",
                "raw": "outputs/flood/MLI/run/raw",
                "rasters": "outputs/flood/MLI/run/rasters",
                "tables": "outputs/flood/MLI/run/tables",
                "qc": "outputs/flood/MLI/run/qc",
                "logs": "outputs/flood/MLI/run/logs",
                "cache": "outputs/_cache/flood/MLI",
            },
            "artifacts": [],
        }
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "run_metadata.json").write_text(json.dumps(payload), encoding="utf-8")
            args = parser.parse_args(
                [
                    "flood-postrun",
                    "--run-dir",
                    str(run_dir),
                    "--skip-parity",
                ]
            )
            rc = args.func(args)
            self.assertEqual(rc, 0)

    def test_violence_postrun_skip_parity_executes(self) -> None:
        parser = build_parser()
        payload = {
            "schema_version": "1.0.0",
            "run_id": "YEM_2025-01-01_2025-12-31_m12_violence",
            "created_utc": "2026-02-24T00:00:00+00:00",
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
                "base": "outputs/violence/YEM/run",
                "raw": "outputs/violence/YEM/run/raw",
                "rasters": "outputs/violence/YEM/run/rasters",
                "tables": "outputs/violence/YEM/run/tables",
                "qc": "outputs/violence/YEM/run/qc",
                "logs": "outputs/violence/YEM/run/logs",
                "cache": "outputs/_cache/violence/YEM",
            },
            "artifacts": [],
        }
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "run_metadata.json").write_text(json.dumps(payload), encoding="utf-8")
            args = parser.parse_args(
                [
                    "violence-postrun",
                    "--run-dir",
                    str(run_dir),
                    "--skip-parity",
                ]
            )
            rc = args.func(args)
            self.assertEqual(rc, 0)

    def test_run_violence_dry_run_executes(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run-violence",
                "--iso3",
                "YEM",
                "--as-of-date",
                "2025-12-31",
                "--admin-path",
                "data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip",
                "--worldpop-path",
                "data/population/yem_pop_2025_CN_100m_R2025A_v1.tif",
                "--dry-run",
            ]
        )
        rc = args.func(args)
        self.assertEqual(rc, 0)

    def test_batch_run_dry_run_executes(self) -> None:
        parser = build_parser()
        with tempfile.TemporaryDirectory() as td:
            readiness = Path(td) / "batch_readiness_report.csv"
            preflight = Path(td) / "batch_preflight_report.csv"
            readiness.write_text(
                (
                    "task_id,iso3,as_of_date,lookback_months,target_adm_level,is_valid_manifest,"
                    "can_run_violence,can_run_spei,can_run_utci,can_run_flood,admin_layer,worldpop_path,acled_path\n"
                    "1,YEM,2025-12-31,12,2,True,True,False,False,False,admin2,/tmp/yem.tif,/tmp/acled_yem.csv\n"
                ),
                encoding="utf-8",
            )
            preflight.write_text(
                (
                    "task_id,violence_preflight_status,spei_preflight_status,utci_preflight_status,flood_preflight_status\n"
                    "1,PASS,SKIP,SKIP,SKIP\n"
                ),
                encoding="utf-8",
            )
            args = parser.parse_args(
                [
                    "batch-run",
                    "--readiness-report",
                    str(readiness),
                    "--preflight-report",
                    str(preflight),
                    "--pipeline",
                    "violence",
                    "--dry-run",
                ]
            )
            rc = args.func(args)
            self.assertEqual(rc, 0)

    def test_run_spei_dry_run_executes(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run-spei",
                "--iso3",
                "YEM",
                "--as-of-date",
                "2025-12-31",
                "--dry-run",
            ]
        )
        rc = args.func(args)
        self.assertEqual(rc, 0)

    def test_run_utci_dry_run_executes(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run-utci",
                "--iso3",
                "YEM",
                "--as-of-date",
                "2025-12-31",
                "--dry-run",
            ]
        )
        rc = args.func(args)
        self.assertEqual(rc, 0)

    def test_run_flood_dry_run_executes(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run-flood",
                "--iso3",
                "YEM",
                "--as-of-date",
                "2025-12-31",
                "--dry-run",
            ]
        )
        rc = args.func(args)
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
