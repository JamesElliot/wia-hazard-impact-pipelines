from __future__ import annotations

import unittest
from pathlib import Path

import jsonschema

from wia_pipelines.config import (
    RunConfig,
    build_run_paths,
    initialize_run_metadata,
    validate_run_metadata,
)


class RunConfigTests(unittest.TestCase):
    def test_run_config_normalizes_iso3_and_hazard(self) -> None:
        config = RunConfig(hazard="FLOOD", iso3="mli", as_of_date="2025-12-31")
        self.assertEqual(config.hazard, "flood")
        self.assertEqual(config.iso3, "MLI")
        self.assertEqual(config.window_end.isoformat(), "2025-12-31")
        self.assertTrue(config.run_id.endswith("_m12_flood"))

    def test_invalid_iso3_raises(self) -> None:
        with self.assertRaises(ValueError):
            RunConfig(hazard="flood", iso3="ML", as_of_date="2025-12-31")

    def test_invalid_hazard_raises(self) -> None:
        with self.assertRaises(ValueError):
            RunConfig(hazard="landslide", iso3="MLI", as_of_date="2025-12-31")

    def test_cyclone_is_supported(self) -> None:
        config = RunConfig(hazard="cyclone", iso3="MOZ", as_of_date="2026-03-31")
        self.assertTrue(config.run_id.endswith("_m12_cyclone"))

    def test_hydrodrought_is_supported(self) -> None:
        config = RunConfig(hazard="hydrodrought", iso3="SOM", as_of_date="2025-12-31")
        self.assertTrue(config.run_id.endswith("_m12_hydrodrought"))

    def test_build_paths_has_contract_keys(self) -> None:
        config = RunConfig(
            hazard="drought",
            iso3="MLI",
            as_of_date="2025-12-31",
            output_root=Path("./outputs"),
        )
        paths = build_run_paths(config)
        expected = {
            "base",
            "raw",
            "intermediate",
            "rasters",
            "tables",
            "qc",
            "logs",
            "maps",
            "cache",
        }
        self.assertEqual(set(paths.keys()), expected)
        self.assertIn("/MLI/2025-12-31_m12/drought", str(paths["base"]))

    def test_metadata_schema_validation(self) -> None:
        config = RunConfig(hazard="heat", iso3="MLI", as_of_date="2025-12-31")
        metadata = initialize_run_metadata(config)
        validate_run_metadata(metadata)

    def test_metadata_schema_rejects_missing_intermediate_path(self) -> None:
        config = RunConfig(hazard="heat", iso3="MLI", as_of_date="2025-12-31")
        metadata = initialize_run_metadata(config)
        del metadata["paths"]["intermediate"]
        with self.assertRaises(jsonschema.exceptions.ValidationError):
            validate_run_metadata(metadata)

    def test_metadata_schema_rejects_missing_top_level_required_keys(self) -> None:
        for key in ("schema_version", "run_id", "created_utc", "run_config", "paths", "artifacts"):
            with self.subTest(key=key):
                config = RunConfig(hazard="heat", iso3="MLI", as_of_date="2025-12-31")
                metadata = initialize_run_metadata(config)
                del metadata[key]
                with self.assertRaises(jsonschema.exceptions.ValidationError):
                    validate_run_metadata(metadata)

    def test_metadata_schema_rejects_missing_run_config_required_keys(self) -> None:
        required = (
            "hazard",
            "iso3",
            "as_of_date",
            "lookback_months",
            "window_start",
            "window_end",
            "target_adm_level",
            "buffer_km",
        )
        for key in required:
            with self.subTest(key=key):
                config = RunConfig(hazard="heat", iso3="MLI", as_of_date="2025-12-31")
                metadata = initialize_run_metadata(config)
                del metadata["run_config"][key]
                with self.assertRaises(jsonschema.exceptions.ValidationError):
                    validate_run_metadata(metadata)

    def test_metadata_schema_rejects_missing_paths_required_keys(self) -> None:
        required = ("base", "raw", "intermediate", "rasters", "tables", "qc", "logs", "maps", "cache")
        for key in required:
            with self.subTest(key=key):
                config = RunConfig(hazard="heat", iso3="MLI", as_of_date="2025-12-31")
                metadata = initialize_run_metadata(config)
                del metadata["paths"][key]
                with self.assertRaises(jsonschema.exceptions.ValidationError):
                    validate_run_metadata(metadata)

    def test_metadata_schema_rejects_wrong_type_for_iso3(self) -> None:
        config = RunConfig(hazard="heat", iso3="MLI", as_of_date="2025-12-31")
        metadata = initialize_run_metadata(config)
        metadata["run_config"]["iso3"] = "ml"  # lowercase, fails the ^[A-Z]{3}$ pattern
        with self.assertRaises(jsonschema.exceptions.ValidationError):
            validate_run_metadata(metadata)

    def _valid_admin_source(self) -> dict:
        return {
            "authority": "COD",
            "vintage": "COD2026-06",
            "access_date": "2026-06-14",
            "path": "/data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip",
            "sha256": "abc123",
            "admin_level": 2,
            "unit_count": 401,
            "pcode_field": "adm2_pcode",
        }

    def test_metadata_schema_admin_source_optional_by_default(self) -> None:
        # A run predating this field, or one where require_admin_source is not
        # requested, must remain schema-valid without it.
        config = RunConfig(hazard="drought", iso3="MLI", as_of_date="2025-12-31")
        metadata = initialize_run_metadata(config)
        validate_run_metadata(metadata)

    def test_metadata_schema_validates_admin_source_when_present(self) -> None:
        config = RunConfig(hazard="drought", iso3="MLI", as_of_date="2025-12-31")
        metadata = initialize_run_metadata(config)
        metadata["admin_source"] = self._valid_admin_source()
        validate_run_metadata(metadata)

    def test_metadata_schema_rejects_incomplete_admin_source(self) -> None:
        config = RunConfig(hazard="drought", iso3="MLI", as_of_date="2025-12-31")
        metadata = initialize_run_metadata(config)
        admin_source = self._valid_admin_source()
        del admin_source["vintage"]
        metadata["admin_source"] = admin_source
        with self.assertRaises(jsonschema.exceptions.ValidationError):
            validate_run_metadata(metadata)

    def test_metadata_schema_rejects_malformed_vintage_token(self) -> None:
        config = RunConfig(hazard="drought", iso3="MLI", as_of_date="2025-12-31")
        metadata = initialize_run_metadata(config)
        admin_source = self._valid_admin_source()
        admin_source["vintage"] = "not-a-vintage"
        metadata["admin_source"] = admin_source
        with self.assertRaises(jsonschema.exceptions.ValidationError):
            validate_run_metadata(metadata)

    def test_require_admin_source_rejects_absence(self) -> None:
        config = RunConfig(hazard="drought", iso3="MLI", as_of_date="2025-12-31")
        metadata = initialize_run_metadata(config)
        with self.assertRaises(jsonschema.exceptions.ValidationError):
            validate_run_metadata(metadata, require_admin_source=True)

    def test_require_admin_source_accepts_presence(self) -> None:
        config = RunConfig(hazard="drought", iso3="MLI", as_of_date="2025-12-31")
        metadata = initialize_run_metadata(config)
        metadata["admin_source"] = self._valid_admin_source()
        validate_run_metadata(metadata, require_admin_source=True)


if __name__ == "__main__":
    unittest.main()
