from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wia_pipelines.batch.manifest import load_batch_manifest


class BatchManifestTests(unittest.TestCase):
    def test_load_manifest_applies_alias_and_default_admin_level(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "batch.csv"
            lk = Path(td) / "iso_lookup.csv"
            p.write_text(
                "ISO3,as_of_date,lookback\n" "LEB,2025-12-31,12\n" "YEM,2025-12-31,12\n",
                encoding="utf-8",
            )
            lk.write_text(
                "Country or Area;M49 Code;ISO-alpha3 Code\n" "Lebanon;422;LBN\n" "Yemen;887;YEM\n",
                encoding="utf-8",
            )
            df = load_batch_manifest(p, default_admin_level=2, iso_lookup_path=lk)
            self.assertEqual(len(df), 2)
            self.assertEqual(df.loc[0, "iso3"], "LBN")
            self.assertTrue(bool(df.loc[0, "iso3_alias_applied"]))
            self.assertEqual(int(df.loc[0, "target_adm_level"]), 2)
            self.assertEqual(str(df.loc[0, "m49_code"]), "422")
            self.assertTrue(bool(df.loc[0, "is_valid_manifest"]))

    def test_manifest_with_invalid_fields_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "batch.csv"
            lk = Path(td) / "iso_lookup.csv"
            p.write_text(
                "ISO3,as_of_date,lookback,admin_level\n" "XX,not-a-date,0,9\n",
                encoding="utf-8",
            )
            lk.write_text(
                "Country or Area;M49 Code;ISO-alpha3 Code\n" "Yemen;887;YEM\n",
                encoding="utf-8",
            )
            df = load_batch_manifest(p, default_admin_level=2, iso_lookup_path=lk)
            self.assertEqual(len(df), 1)
            self.assertFalse(bool(df.loc[0, "is_valid_manifest"]))
            self.assertIn("as_of_date", str(df.loc[0, "manifest_errors"]))

    def test_load_manifest_drops_blank_rows_and_cleans_numeric_m49(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "batch.csv"
            p.write_text(
                "ISO3,as_of_date,lookback,admin_level,m49_code\n" "MMR,2025-12-31,12,3,104\n" ",,,,\n",
                encoding="utf-8",
            )
            df = load_batch_manifest(p, default_admin_level=2, iso_lookup_path=None)
            self.assertEqual(len(df), 1)
            self.assertEqual(str(df.loc[0, "m49_code"]), "104")
            self.assertEqual(int(df.loc[0, "target_adm_level"]), 3)
            self.assertTrue(bool(df.loc[0, "is_valid_manifest"]))


if __name__ == "__main__":
    unittest.main()
