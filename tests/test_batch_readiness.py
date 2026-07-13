from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box

from wia_pipelines.batch.readiness import evaluate_batch_readiness


class BatchReadinessTests(unittest.TestCase):
    def test_readiness_flags_worldpop_and_admin_and_acled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            admin_path = root / "admin.gpkg"
            wp_dir = root / "population"
            acled_dir = root / "violence"
            wp_dir.mkdir(parents=True, exist_ok=True)
            acled_dir.mkdir(parents=True, exist_ok=True)

            admin2 = gpd.GeoDataFrame(
                {"iso3": ["YEM"], "adm2_pcode": ["YEM001"], "geometry": [box(0, 0, 1, 1)]},
                crs="EPSG:4326",
            )
            admin2.to_file(admin_path, layer="admin2", driver="GPKG")

            (wp_dir / "yem_pop_2025_CN_100m_R2025A_v1.tif").write_bytes(b"x")
            (acled_dir / "acled_yem_20250101-20251231.csv").write_text(
                "latitude,longitude,event_date,event_type\n", encoding="utf-8"
            )

            tasks = pd.DataFrame(
                [
                    {
                        "task_id": 1,
                        "iso3_input": "YEM",
                        "iso3": "YEM",
                        "iso3_alias_applied": False,
                        "as_of_date": "2025-12-31",
                        "lookback_months": 12,
                        "m49_code": "887",
                        "target_adm_level": 2,
                        "is_valid_manifest": True,
                        "manifest_errors": "",
                    }
                ]
            )

            out = evaluate_batch_readiness(
                tasks=tasks,
                admin_path=admin_path,
                worldpop_dir=wp_dir,
                acled_dir=acled_dir,
            )
            self.assertEqual(len(out), 1)
            self.assertTrue(bool(out.loc[0, "worldpop_exists"]))
            self.assertTrue(bool(out.loc[0, "admin_layer_exists"]))
            self.assertTrue(bool(out.loc[0, "admin_feature_count"] > 0))
            self.assertTrue(bool(out.loc[0, "acled_exists"]))
            self.assertTrue(bool(out.loc[0, "readiness_ok_all"]))

    def test_readiness_builds_country_acled_from_bulk(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            admin_path = root / "admin.gpkg"
            wp_dir = root / "population"
            acled_dir = root / "violence"
            wp_dir.mkdir(parents=True, exist_ok=True)
            acled_dir.mkdir(parents=True, exist_ok=True)

            admin2 = gpd.GeoDataFrame(
                {"iso3": ["YEM"], "adm2_pcode": ["YEM001"], "geometry": [box(0, 0, 1, 1)]},
                crs="EPSG:4326",
            )
            admin2.to_file(admin_path, layer="admin2", driver="GPKG")

            (wp_dir / "yem_pop_2025_CN_100m_R2025A_v1.tif").write_bytes(b"x")
            bulk = acled_dir / "acled_all_20250101-20251231.csv"
            bulk.write_text(
                "iso,iso3,latitude,longitude,event_date,event_type\n"
                "887,YEM,15.3,44.2,2025-06-01,Battles\n"
                "887,YEM,15.6,44.4,2025-10-12,Riots\n",
                encoding="utf-8",
            )

            tasks = pd.DataFrame(
                [
                    {
                        "task_id": 1,
                        "iso3_input": "YEM",
                        "iso3": "YEM",
                        "iso3_alias_applied": False,
                        "as_of_date": "2025-12-31",
                        "lookback_months": 12,
                        "m49_code": "887",
                        "target_adm_level": 2,
                        "is_valid_manifest": True,
                        "manifest_errors": "",
                    }
                ]
            )

            out = evaluate_batch_readiness(
                tasks=tasks,
                admin_path=admin_path,
                worldpop_dir=wp_dir,
                acled_dir=acled_dir,
                bulk_acled_path=bulk,
                create_country_acled_from_bulk=True,
            )
            expected_country = acled_dir / "acled_yem_20250101-20251231.csv"
            self.assertTrue(expected_country.exists())
            self.assertTrue(bool(out.loc[0, "acled_exists"]))
            self.assertEqual(Path(out.loc[0, "acled_path"]), expected_country)

    def test_readiness_reports_invalid_manifest_without_casting_missing_level(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tasks = pd.DataFrame(
                [
                    {
                        "task_id": 1,
                        "iso3_input": "",
                        "iso3": "",
                        "iso3_alias_applied": False,
                        "as_of_date": "",
                        "lookback_months": None,
                        "m49_code": "",
                        "target_adm_level": None,
                        "is_valid_manifest": False,
                        "manifest_errors": "admin_level is missing",
                    }
                ]
            )

            out = evaluate_batch_readiness(
                tasks=tasks,
                admin_path=root / "missing.gpkg",
                worldpop_dir=root / "population",
                acled_dir=root / "violence",
            )

            self.assertEqual(len(out), 1)
            self.assertFalse(bool(out.loc[0, "readiness_ok_all"]))
            self.assertIn("admin_level is missing", str(out.loc[0, "readiness_issues"]))


if __name__ == "__main__":
    unittest.main()
