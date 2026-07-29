from __future__ import annotations

import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

from wia_pipelines.core.admin import (
    admin_bounds_hash,
    build_admin_aoi,
    filter_admin_for_iso3,
    load_admin_layer,
)

HAS_GEO = all(importlib.util.find_spec(m) is not None for m in ("geopandas", "shapely", "pyproj", "fiona"))


@unittest.skipUnless(HAS_GEO, "geospatial stack not installed")
class AdminTests(unittest.TestCase):
    def test_load_filter_aoi_hash(self) -> None:
        import geopandas as gpd
        from shapely.geometry import box

        with tempfile.TemporaryDirectory() as td:
            gpkg = Path(td) / "admin.gpkg"
            gdf = gpd.GeoDataFrame(
                {
                    "iso3": ["AAA", "AAA", "BBB"],
                    "adm_level": [2, 2, 2],
                    "geometry": [box(0, 0, 1, 1), box(1, 0, 2, 1), box(10, 10, 11, 11)],
                },
                crs="EPSG:4326",
            )
            gdf.to_file(gpkg, layer="admin2", driver="GPKG")

            loaded = load_admin_layer(gpkg, layer="admin2")
            filtered = filter_admin_for_iso3(
                loaded, "AAA", iso3_field="iso3", adm_level_field="adm_level", target_adm_level=2
            )
            aoi = build_admin_aoi(filtered, buffer_km=0.0, out_crs="EPSG:4326")
            self.assertEqual(len(filtered), 2)
            self.assertEqual(len(aoi["admin_bounds"]), 4)
            h = admin_bounds_hash("AAA", aoi["admin_bounds"])
            self.assertEqual(len(h), 64)

    def test_load_admin_layer_missing_path_raises_file_not_found(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_admin_layer(Path("/nonexistent/admin.gpkg"), layer="admin2")

    def test_load_admin_layer_reads_zip_wrapped_source(self) -> None:
        import geopandas as gpd
        from shapely.geometry import box

        with tempfile.TemporaryDirectory() as td:
            gpkg = Path(td) / "admin.gpkg"
            gdf = gpd.GeoDataFrame(
                {"iso3": ["AAA"], "geometry": [box(0, 0, 1, 1)]},
                crs="EPSG:4326",
            )
            gdf.to_file(gpkg, layer="admin2", driver="GPKG")
            zip_path = Path(td) / "admin.gpkg.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.write(gpkg, arcname="admin.gpkg")

            loaded = load_admin_layer(zip_path, layer="admin2")
            self.assertEqual(len(loaded), 1)

    def test_load_admin_layer_falls_back_when_named_layer_is_missing(self) -> None:
        import geopandas as gpd
        from shapely.geometry import box

        with tempfile.TemporaryDirectory() as td:
            gpkg = Path(td) / "admin.gpkg"
            gdf = gpd.GeoDataFrame(
                {"iso3": ["AAA"], "geometry": [box(0, 0, 1, 1)]},
                crs="EPSG:4326",
            )
            gdf.to_file(gpkg, layer="admin2", driver="GPKG")

            # Requesting a layer name that doesn't exist should fall back to
            # a plain (no-layer) read instead of raising.
            loaded = load_admin_layer(gpkg, layer="does_not_exist")
            self.assertEqual(len(loaded), 1)

    def test_build_admin_aoi_reprojects_non_4326_input(self) -> None:
        import geopandas as gpd
        from pyproj import Transformer
        from shapely.geometry import box

        # A 1x1 degree box at lon/lat [0,1]x[0,1], expressed in Web Mercator.
        to_3857 = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
        x0, y0 = to_3857.transform(0, 0)
        x1, y1 = to_3857.transform(1, 1)
        admin_3857 = gpd.GeoDataFrame(
            {"iso3": ["AAA"], "geometry": [box(x0, y0, x1, y1)]},
            crs="EPSG:3857",
        )

        aoi = build_admin_aoi(admin_3857, buffer_km=0.0, out_crs="EPSG:4326")
        west, south, east, north = aoi["admin_bounds"]
        self.assertAlmostEqual(west, 0.0, places=6)
        self.assertAlmostEqual(south, 0.0, places=6)
        self.assertAlmostEqual(east, 1.0, places=6)
        self.assertAlmostEqual(north, 1.0, places=6)

    def test_build_admin_aoi_rejects_missing_crs(self) -> None:
        import geopandas as gpd
        from shapely.geometry import box

        admin_no_crs = gpd.GeoDataFrame({"iso3": ["AAA"], "geometry": [box(0, 0, 1, 1)]})
        with self.assertRaises(ValueError):
            build_admin_aoi(admin_no_crs, buffer_km=0.0, out_crs="EPSG:4326")


if __name__ == "__main__":
    unittest.main()
