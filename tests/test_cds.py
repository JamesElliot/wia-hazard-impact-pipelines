from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from wia_pipelines.core.cds import ensure_downloads, extract_zip_to_dir, months_for_last_n


class CdsTests(unittest.TestCase):
    def test_months_for_last_n(self) -> None:
        months = months_for_last_n("2025-12-31", n_months=3)
        self.assertEqual(months, [(2025, 10), (2025, 11), (2025, 12)])

    def test_extract_zip_to_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            zip_path = td_path / "demo.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("a.nc", "dummy")
                zf.writestr("sub/b.nc", "dummy")
            out = extract_zip_to_dir(zip_path, td_path / "extract")
            self.assertEqual(len(out), 2)
            self.assertTrue(all(p.suffix == ".nc" for p in out))

    def test_ensure_downloads_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            manifest = [
                {"request_id": "1", "ok": True, "error": None},
                {"request_id": "2", "ok": False, "error": "bad"},
            ]
            out = ensure_downloads(manifest, "spei", Path(td))
            self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
