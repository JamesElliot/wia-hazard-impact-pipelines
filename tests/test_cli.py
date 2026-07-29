from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from wia_pipelines.cli import _add_common_hazard_paths, _add_iso3_window_args, build_parser


class SharedArgparseHelperTests(unittest.TestCase):
    def test_add_iso3_window_args_defaults(self) -> None:
        parser = argparse.ArgumentParser()
        _add_iso3_window_args(parser)
        args = parser.parse_args(["--iso3", "MOZ", "--as-of-date", "2026-03-31"])
        self.assertEqual(args.iso3, "MOZ")
        self.assertEqual(args.as_of_date, "2026-03-31")
        self.assertEqual(args.lookback_months, 12)

    def test_add_iso3_window_args_requires_iso3_and_as_of_date(self) -> None:
        parser = argparse.ArgumentParser(exit_on_error=False)
        _add_iso3_window_args(parser)
        with self.assertRaises((SystemExit, argparse.ArgumentError)):
            parser.parse_args([])

    def test_add_iso3_window_args_custom_help_text(self) -> None:
        parser = argparse.ArgumentParser()
        _add_iso3_window_args(parser, as_of_date_help="Inclusive YYYY-MM-DD end date")
        action = next(a for a in parser._actions if a.dest == "as_of_date")
        self.assertEqual(action.help, "Inclusive YYYY-MM-DD end date")

    def test_add_common_hazard_paths_defaults(self) -> None:
        parser = argparse.ArgumentParser()
        _add_common_hazard_paths(parser)
        args = parser.parse_args([])
        self.assertEqual(args.output_root, "./outputs")
        self.assertEqual(
            args.admin_path,
            "./data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip",
        )
        self.assertIsNone(args.worldpop_path)
        self.assertEqual(args.worldpop_dir, "./data/population")


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

    def test_cyclone_and_earthquake_share_minimal_run_arguments(self) -> None:
        parser = build_parser()
        for command in ("run-cyclone", "run-earthquake"):
            args = parser.parse_args([command, "--iso3", "MOZ", "--as-of-date", "2026-03-31", "--dry-run"])
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
                "base": "outputs/MLI/2025-12-31_m12/flood",
                "raw": "outputs/MLI/2025-12-31_m12/flood/raw",
                "intermediate": "outputs/MLI/2025-12-31_m12/flood/intermediate",
                "rasters": "outputs/MLI/2025-12-31_m12/flood/rasters",
                "tables": "outputs/MLI/2025-12-31_m12/flood/tables",
                "qc": "outputs/MLI/2025-12-31_m12/flood/qc",
                "logs": "outputs/MLI/2025-12-31_m12/flood/logs",
                "maps": "outputs/MLI/2025-12-31_m12/flood/maps",
                "cache": "outputs/_cache/MLI/flood",
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
                "base": "outputs/MLI/2025-12-31_m12/flood",
                "raw": "outputs/MLI/2025-12-31_m12/flood/raw",
                "intermediate": "outputs/MLI/2025-12-31_m12/flood/intermediate",
                "rasters": "outputs/MLI/2025-12-31_m12/flood/rasters",
                "tables": "outputs/MLI/2025-12-31_m12/flood/tables",
                "qc": "outputs/MLI/2025-12-31_m12/flood/qc",
                "logs": "outputs/MLI/2025-12-31_m12/flood/logs",
                "maps": "outputs/MLI/2025-12-31_m12/flood/maps",
                "cache": "outputs/_cache/MLI/flood",
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

    def test_postrun_defaults_to_strict_metadata_validation(self) -> None:
        # ARCH-008: a schema-invalid run_metadata.json must fail postrun QC
        # by default (previously only a warning unless the caller opted in
        # with --strict-metadata-validation) -- the same schema is a hard
        # `raise` during the pipeline run itself, so postrun silently
        # downgrading it to a warning made corrupted metadata pass QC.
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
                # Deliberately missing "intermediate" and "maps" to trip schema validation.
                "base": "outputs/MLI/2025-12-31_m12/flood",
                "raw": "outputs/MLI/2025-12-31_m12/flood/raw",
                "rasters": "outputs/MLI/2025-12-31_m12/flood/rasters",
                "tables": "outputs/MLI/2025-12-31_m12/flood/tables",
                "qc": "outputs/MLI/2025-12-31_m12/flood/qc",
                "logs": "outputs/MLI/2025-12-31_m12/flood/logs",
                "cache": "outputs/_cache/MLI/flood",
            },
            "artifacts": [],
        }
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "run_metadata.json").write_text(json.dumps(payload), encoding="utf-8")

            args = parser.parse_args(["flood-postrun", "--run-dir", str(run_dir), "--skip-parity"])
            rc = args.func(args)
            self.assertEqual(rc, 2, "corrupted metadata must fail postrun by default")

            args_opt_out = parser.parse_args(
                [
                    "flood-postrun",
                    "--run-dir",
                    str(run_dir),
                    "--skip-parity",
                    "--no-strict-metadata-validation",
                ]
            )
            rc_opt_out = args_opt_out.func(args_opt_out)
            self.assertEqual(rc_opt_out, 0, "explicit opt-out must still allow a warning-only pass")

    def test_spei_postrun_skip_parity_executes(self) -> None:
        parser = build_parser()
        payload = {
            "schema_version": "1.0.0",
            "run_id": "MLI_2025-01-01_2025-12-31_m12_drought",
            "created_utc": "2026-02-24T00:00:00+00:00",
            "run_config": {
                "hazard": "drought",
                "iso3": "MLI",
                "as_of_date": "2025-12-31",
                "lookback_months": 12,
                "window_start": "2025-01-01",
                "window_end": "2025-12-31",
                "target_adm_level": 2,
                "buffer_km": 0.0,
            },
            "paths": {
                "base": "outputs/MLI/2025-12-31_m12/drought",
                "raw": "outputs/MLI/2025-12-31_m12/drought/raw",
                "intermediate": "outputs/MLI/2025-12-31_m12/drought/intermediate",
                "rasters": "outputs/MLI/2025-12-31_m12/drought/rasters",
                "tables": "outputs/MLI/2025-12-31_m12/drought/tables",
                "qc": "outputs/MLI/2025-12-31_m12/drought/qc",
                "logs": "outputs/MLI/2025-12-31_m12/drought/logs",
                "maps": "outputs/MLI/2025-12-31_m12/drought/maps",
                "cache": "outputs/_cache/MLI/drought",
            },
            "artifacts": [],
        }
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "run_metadata.json").write_text(json.dumps(payload), encoding="utf-8")
            args = parser.parse_args(
                [
                    "spei-postrun",
                    "--run-dir",
                    str(run_dir),
                    "--skip-parity",
                ]
            )
            rc = args.func(args)
            self.assertEqual(rc, 0)
            self.assertFalse((run_dir / "qc" / "spei").exists())

    def test_utci_postrun_skip_parity_executes(self) -> None:
        parser = build_parser()
        payload = {
            "schema_version": "1.0.0",
            "run_id": "MLI_2025-01-01_2025-12-31_m12_heat",
            "created_utc": "2026-02-24T00:00:00+00:00",
            "run_config": {
                "hazard": "heat",
                "iso3": "MLI",
                "as_of_date": "2025-12-31",
                "lookback_months": 12,
                "window_start": "2025-01-01",
                "window_end": "2025-12-31",
                "target_adm_level": 2,
                "buffer_km": 0.0,
            },
            "paths": {
                "base": "outputs/MLI/2025-12-31_m12/heat",
                "raw": "outputs/MLI/2025-12-31_m12/heat/raw",
                "intermediate": "outputs/MLI/2025-12-31_m12/heat/intermediate",
                "rasters": "outputs/MLI/2025-12-31_m12/heat/rasters",
                "tables": "outputs/MLI/2025-12-31_m12/heat/tables",
                "qc": "outputs/MLI/2025-12-31_m12/heat/qc",
                "logs": "outputs/MLI/2025-12-31_m12/heat/logs",
                "maps": "outputs/MLI/2025-12-31_m12/heat/maps",
                "cache": "outputs/_cache/MLI/heat",
            },
            "artifacts": [],
        }
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "run_metadata.json").write_text(json.dumps(payload), encoding="utf-8")
            args = parser.parse_args(
                [
                    "utci-postrun",
                    "--run-dir",
                    str(run_dir),
                    "--skip-parity",
                ]
            )
            rc = args.func(args)
            self.assertEqual(rc, 0)
            self.assertFalse((run_dir / "qc" / "utci").exists())

    def test_hydrodrought_postrun_skip_parity_executes(self) -> None:
        parser = build_parser()
        payload = {
            "schema_version": "1.1.0",
            "run_id": "SOM_2025-01-01_2025-12-31_m12_hydrodrought",
            "created_utc": "2026-02-24T00:00:00+00:00",
            "run_config": {
                "hazard": "hydrodrought",
                "iso3": "SOM",
                "as_of_date": "2025-12-31",
                "lookback_months": 12,
                "window_start": "2025-01-01",
                "window_end": "2025-12-31",
                "target_adm_level": 2,
                "buffer_km": 0.0,
            },
            "paths": {
                "base": "outputs/SOM/2025-12-31_m12/hydrodrought",
                "raw": "outputs/SOM/2025-12-31_m12/hydrodrought/raw",
                "intermediate": "outputs/SOM/2025-12-31_m12/hydrodrought/intermediate",
                "rasters": "outputs/SOM/2025-12-31_m12/hydrodrought/rasters",
                "tables": "outputs/SOM/2025-12-31_m12/hydrodrought/tables",
                "qc": "outputs/SOM/2025-12-31_m12/hydrodrought/qc",
                "logs": "outputs/SOM/2025-12-31_m12/hydrodrought/logs",
                "maps": "outputs/SOM/2025-12-31_m12/hydrodrought/maps",
                "cache": "outputs/_cache/SOM/hydrodrought",
            },
            "artifacts": [],
        }
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "run_metadata.json").write_text(json.dumps(payload), encoding="utf-8")
            args = parser.parse_args(
                [
                    "hydrodrought-postrun",
                    "--run-dir",
                    str(run_dir),
                    "--skip-parity",
                ]
            )
            rc = args.func(args)
            self.assertEqual(rc, 0)
            self.assertFalse((run_dir / "qc" / "hydrodrought").exists())

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
                "intermediate": "outputs/violence/YEM/run/intermediate",
                "rasters": "outputs/violence/YEM/run/rasters",
                "tables": "outputs/violence/YEM/run/tables",
                "qc": "outputs/violence/YEM/run/qc",
                "logs": "outputs/violence/YEM/run/logs",
                "maps": "outputs/violence/YEM/run/maps",
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
