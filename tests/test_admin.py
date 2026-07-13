from __future__ import annotations

import importlib.util
import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
