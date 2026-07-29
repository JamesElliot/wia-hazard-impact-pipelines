from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from wia_pipelines.core.cds import (
    download_cds,
    download_month_with_fallback,
    ensure_downloads,
    extract_zip_to_dir,
    months_for_last_n,
)


def _request_builder(year: int, month: int, tier: str) -> dict:
    return {"year": year, "month": month, "dataset_type": tier}


class CdsTests(unittest.TestCase):
    def test_months_for_last_n(self) -> None:
        months = months_for_last_n("2025-12-31", n_months=3)
        self.assertEqual(months, [(2025, 10), (2025, 11), (2025, 12)])

    def test_download_cds_maps_client_exception_to_failure_tuple(self) -> None:
        # The network boundary itself (cdsapi.Client construction/retrieve)
        # is never exercised by the higher-level fallback tests below, which
        # all mock download_cds as a whole -- this confirms the actual
        # try/except around the client call turns a raised exception into a
        # (False, message) tuple rather than propagating a raw traceback.
        class _RaisingClient:
            def __init__(self, *args, **kwargs):
                raise ConnectionError("simulated CDS network failure")

        fake_cdsapi = type("fake_cdsapi", (), {"Client": _RaisingClient})

        with tempfile.TemporaryDirectory() as td:
            out_zip = Path(td) / "out.zip"
            with patch("wia_pipelines.core.cds._require", return_value=fake_cdsapi):
                ok, err = download_cds("some-dataset", {"a": 1}, out_zip)
            self.assertFalse(ok)
            self.assertIn("simulated CDS network failure", err)

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

    def test_download_month_with_fallback_uses_cached_consolidated_tier(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cons = Path(td) / "cons.zip"
            cons.write_bytes(b"x" * 10)
            intermediate = Path(td) / "int.zip"
            with patch("wia_pipelines.core.cds.download_cds") as mock_dl:
                ok, rows = download_month_with_fallback(
                    "dataset", _request_builder, cons, intermediate, "dataset_type", 2025, 1
                )
            self.assertTrue(ok)
            mock_dl.assert_not_called()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["dataset_type"], "consolidated_dataset")
            self.assertTrue(rows[0]["cached"])

    def test_download_month_with_fallback_skips_intermediate_when_consolidated_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cons = Path(td) / "cons.zip"
            intermediate = Path(td) / "int.zip"
            with patch("wia_pipelines.core.cds.download_cds", return_value=(True, None)) as mock_dl:
                ok, rows = download_month_with_fallback(
                    "dataset", _request_builder, cons, intermediate, "dataset_type", 2025, 2
                )
            self.assertTrue(ok)
            self.assertEqual(mock_dl.call_count, 1)
            self.assertEqual(len(rows), 1)

    def test_download_month_with_fallback_falls_back_to_cached_intermediate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cons = Path(td) / "cons.zip"
            intermediate = Path(td) / "int.zip"
            intermediate.write_bytes(b"y" * 5)
            with patch("wia_pipelines.core.cds.download_cds", return_value=(False, "boom")) as mock_dl:
                ok, rows = download_month_with_fallback(
                    "dataset", _request_builder, cons, intermediate, "dataset_type", 2025, 3
                )
            self.assertTrue(ok)
            self.assertEqual(mock_dl.call_count, 1)
            self.assertEqual(len(rows), 2)
            self.assertFalse(rows[0]["ok"])
            self.assertEqual(rows[0]["dataset_type"], "consolidated_dataset")
            self.assertTrue(rows[1]["ok"])
            self.assertTrue(rows[1]["cached"])
            self.assertEqual(rows[1]["dataset_type"], "intermediate_dataset")

    def test_download_month_with_fallback_reports_failure_when_both_tiers_fail(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cons = Path(td) / "cons.zip"
            intermediate = Path(td) / "int.zip"
            with patch("wia_pipelines.core.cds.download_cds", return_value=(False, "nope")) as mock_dl:
                ok, rows = download_month_with_fallback(
                    "dataset", _request_builder, cons, intermediate, "dataset_type", 2025, 4
                )
            self.assertFalse(ok)
            self.assertEqual(mock_dl.call_count, 2)
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(not row["ok"] for row in rows))


if __name__ == "__main__":
    unittest.main()
