from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wia_pipelines.hazards.utci import (
    UtciRunInputs,
    build_utci_run_context,
)


class UtciHazardTests(unittest.TestCase):
    def test_build_utci_run_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx = build_utci_run_context(
                UtciRunInputs(
                    iso3="MLI",
                    as_of_date="2025-12-31",
                    lookback_months=12,
                    output_root=Path(td),
                ),
                create_dirs=True,
                write_metadata=True,
            )
            self.assertEqual(ctx["config"].hazard, "heat")
            self.assertTrue((ctx["layout"]["base"] / "run_metadata.json").exists())


if __name__ == "__main__":
    unittest.main()
