from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Polygon, box

from wia_pipelines.hazards._admin_config import actual_column, load_yaml_hazard_admin


def _admin_config(**overrides) -> dict:
    config = {
        "level": 2,
        "layer": None,
        "fields": {
            "iso3": "ISO3",
            "adm0_pcode": "ADM0_PCODE",
            "adm2_pcode": "ADM2_PCODE",
        },
    }
    config.update(overrides)
    return config


class ActualColumnTests(unittest.TestCase):
    def test_returns_none_for_falsy_configured(self) -> None:
        self.assertIsNone(actual_column(["A", "B"], None))
        self.assertIsNone(actual_column(["A", "B"], ""))

    def test_exact_match_returned_as_is(self) -> None:
        self.assertEqual(actual_column(["ISO3", "ADM2_PCODE"], "ISO3"), "ISO3")

    def test_case_insensitive_match(self) -> None:
        self.assertEqual(actual_column(["iso3", "adm2_pcode"], "ISO3"), "iso3")

    def test_no_match_returns_none(self) -> None:
        self.assertIsNone(actual_column(["FOO", "BAR"], "ISO3"))


class LoadYamlHazardAdminTests(unittest.TestCase):
    def _write_admin(self, path: Path, columns: dict, geometries: list) -> None:
        gdf = gpd.GeoDataFrame({**columns, "geometry": geometries}, crs="EPSG:4326")
        gdf.to_file(path, driver="GPKG")

    def test_filters_by_iso3_field_and_resolves_case_insensitive_columns(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "admin.gpkg"
            self._write_admin(
                path,
                {
                    "iso3": ["AAA", "BBB"],
                    "adm0_pcode": ["AAA", "BBB"],
                    "adm2_pcode": ["AAA001", "BBB001"],
                },
                [box(0, 0, 1, 1), box(1, 1, 2, 2)],
            )
            config = _admin_config()
            admin = load_yaml_hazard_admin(path, "AAA", config)
            self.assertEqual(len(admin), 1)
            self.assertEqual(admin.iloc[0]["adm2_pcode"], "AAA001")
            # fields is mutated in place to the resolved (lowercase, on-disk) names.
            self.assertEqual(config["fields"]["iso3"], "iso3")
            self.assertEqual(config["fields"]["adm2_pcode"], "adm2_pcode")

    def test_falls_back_to_adm0_pcode_prefix_when_iso3_field_absent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "admin.gpkg"
            self._write_admin(
                path,
                {"ADM0_PCODE": ["AAA", "BBB"], "ADM2_PCODE": ["AAA001", "BBB001"]},
                [box(0, 0, 1, 1), box(1, 1, 2, 2)],
            )
            config = _admin_config()
            admin = load_yaml_hazard_admin(path, "AAA", config)
            self.assertEqual(len(admin), 1)
            self.assertEqual(admin.iloc[0]["ADM2_PCODE"], "AAA001")

    def test_empty_subset_via_iso3_field_raises_with_field_specific_message(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "admin.gpkg"
            self._write_admin(
                path,
                {"iso3": ["BBB"], "adm0_pcode": ["BBB"], "adm2_pcode": ["BBB001"]},
                [box(0, 0, 1, 1)],
            )
            config = _admin_config()
            with self.assertRaisesRegex(ValueError, "No admin features match ISO3 AAA in field"):
                load_yaml_hazard_admin(path, "AAA", config)

    def test_empty_subset_via_adm0_pcode_prefix_raises_with_column_specific_message(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "admin.gpkg"
            self._write_admin(
                path,
                {"ADM0_PCODE": ["BBB"], "ADM2_PCODE": ["BBB001"]},
                [box(0, 0, 1, 1)],
            )
            config = _admin_config()
            with self.assertRaisesRegex(ValueError, "No admin features match ISO3 AAA by .* prefix"):
                load_yaml_hazard_admin(path, "AAA", config)

    def test_missing_configured_pcode_column_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "admin.gpkg"
            self._write_admin(
                path,
                {"iso3": ["AAA"], "adm0_pcode": ["AAA"]},
                [box(0, 0, 1, 1)],
            )
            config = _admin_config()
            with self.assertRaisesRegex(ValueError, "missing configured admin-2 key"):
                load_yaml_hazard_admin(path, "AAA", config)

    def test_duplicate_pcode_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "admin.gpkg"
            self._write_admin(
                path,
                {
                    "iso3": ["AAA", "AAA"],
                    "adm0_pcode": ["AAA", "AAA"],
                    "adm2_pcode": ["AAA001", "AAA001"],
                },
                [box(0, 0, 1, 1), box(1, 1, 2, 2)],
            )
            config = _admin_config()
            with self.assertRaisesRegex(ValueError, "must be present and unique"):
                load_yaml_hazard_admin(path, "AAA", config)

    def test_drops_null_and_empty_geometries_and_makes_valid(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "admin.gpkg"
            bowtie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
            gdf = gpd.GeoDataFrame(
                {
                    "iso3": ["AAA", "AAA", "AAA"],
                    "adm0_pcode": ["AAA", "AAA", "AAA"],
                    "adm2_pcode": ["AAA001", "AAA002", "AAA003"],
                },
                geometry=[bowtie, Polygon(), None],
                crs="EPSG:4326",
            )
            gdf.to_file(path, driver="GPKG")
            config = _admin_config()
            admin = load_yaml_hazard_admin(path, "AAA", config)
            # Empty/null geometries dropped; only the bowtie polygon (now valid) remains.
            self.assertEqual(len(admin), 1)
            self.assertEqual(admin.iloc[0]["adm2_pcode"], "AAA001")
            self.assertTrue(admin.iloc[0].geometry.is_valid)

    def test_empty_admin_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "admin.gpkg"
            gdf = gpd.GeoDataFrame(
                {"iso3": [], "adm0_pcode": [], "adm2_pcode": []}, geometry=[], crs="EPSG:4326"
            )
            gdf.to_file(path, driver="GPKG")
            config = _admin_config()
            with self.assertRaisesRegex(ValueError, "must contain features"):
                load_yaml_hazard_admin(path, "AAA", config)


if __name__ == "__main__":
    unittest.main()
