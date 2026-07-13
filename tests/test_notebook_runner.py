from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from wia_pipelines.notebook_runner import parameterize_notebook


class NotebookRunnerTests(unittest.TestCase):
    def test_parameterize_notebook_replaces_assignments(self) -> None:
        payload = {
            "cells": [
                {
                    "cell_type": "code",
                    "source": ('ISO3 = "HTI"\n' 'AS_OF_DATE = "2025-12-31"\n' "LOOKBACK_MONTHS = 12\n"),
                }
            ]
        }
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "in.ipynb"
            out_dir = Path(td) / "out"
            src.write_text(json.dumps(payload), encoding="utf-8")
            out_path, counts = parameterize_notebook(
                source_nb=src,
                out_dir=out_dir,
                replacements={
                    "ISO3": '"YEM"',
                    "AS_OF_DATE": '"2026-01-01"',
                    "LOOKBACK_MONTHS": "6",
                },
            )
            self.assertTrue(out_path.exists())
            self.assertEqual(counts["ISO3"], 1)
            patched = json.loads(out_path.read_text(encoding="utf-8"))
            src_text = "".join(patched["cells"][0]["source"])
            self.assertIn('ISO3 = "YEM"', src_text)
            self.assertIn('AS_OF_DATE = "2026-01-01"', src_text)
            self.assertIn("LOOKBACK_MONTHS = 6", src_text)


if __name__ == "__main__":
    unittest.main()
