from __future__ import annotations

import unittest
from pathlib import Path

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

    def test_build_paths_has_contract_keys(self) -> None:
        config = RunConfig(
            hazard="drought",
            iso3="MLI",
            as_of_date="2025-12-31",
            output_root=Path("./outputs"),
        )
        paths = build_run_paths(config)
        expected = {"base", "raw", "rasters", "tables", "qc", "logs", "cache"}
        self.assertEqual(set(paths.keys()), expected)
        self.assertIn("/drought/MLI/", str(paths["base"]))

    def test_metadata_schema_validation(self) -> None:
        config = RunConfig(hazard="heat", iso3="MLI", as_of_date="2025-12-31")
        metadata = initialize_run_metadata(config)
        validate_run_metadata(metadata)


if __name__ == "__main__":
    unittest.main()
