from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from wia_pipelines.hazards.script_runs import run_notebook_hazard_pipeline


class ScriptRunsTests(unittest.TestCase):
    def test_run_notebook_hazard_pipeline_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            nb = Path(td) / "mini.ipynb"
            nb.write_text(
                json.dumps(
                    {
                        "cells": [
                            {
                                "cell_type": "code",
                                "source": 'ISO3 = "XXX"\nAS_OF_DATE = "2025-01-01"\nLOOKBACK_MONTHS = 12\n',
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            rc, payload = run_notebook_hazard_pipeline(
                pipeline_name="spei",
                notebook_path=nb,
                iso3="YEM",
                as_of_date="2025-12-31",
                lookback_months=12,
                output_root=Path(td) / "out",
                admin_path=Path(td) / "admin.zip",
                target_adm_level=2,
                dry_run=True,
                timeout_seconds=0,
            )
            self.assertEqual(rc, 0)
            self.assertEqual(payload["status"], "DRY_RUN")
            self.assertTrue(Path(payload["notebook_parameterized"]).exists())


if __name__ == "__main__":
    unittest.main()
