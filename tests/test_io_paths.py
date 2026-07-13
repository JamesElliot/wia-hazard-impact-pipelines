from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wia_pipelines.core.io_paths import (
    append_artifact,
    build_run_layout,
    create_run_dirs,
    write_json,
)


class IoPathsTests(unittest.TestCase):
    def test_build_and_create_layout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            layout = build_run_layout(
                output_root=Path(td),
                hazard="flood",
                iso3="mli",
                run_id="MLI_2025-01-01_2025-12-31_m12_flood",
            )
            self.assertIn("logs", layout)
            create_run_dirs(layout)
            for path in layout.values():
                self.assertTrue(path.exists())

    def test_write_json_and_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "logs" / "run_metadata.json"
            payload = {"artifacts": []}
            append_artifact(payload, "demo", Path("/tmp/demo.txt"), "note")
            write_json(out, payload)
            self.assertTrue(out.exists())
            self.assertEqual(payload["artifacts"][0]["kind"], "demo")


if __name__ == "__main__":
    unittest.main()
