from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from wia_pipelines.core.admin import admin_bounds_hash, build_admin_aoi, filter_admin_for_iso3
from wia_pipelines.core.aggregation import zonal_sum
from wia_pipelines.core.raster_ops import align_to_reference, write_array_geotiff

HAS_SMOKE = all(
    importlib.util.find_spec(m) is not None
    for m in ("numpy", "rasterio", "geopandas", "shapely", "pyproj", "fiona")
)


@unittest.skipUnless(HAS_SMOKE, "full geospatial stack not installed")
class SmokeToyPipelineTests(unittest.TestCase):
    def test_aoi_bounds_hash_align_and_aggregate(self) -> None:
        import geopandas as gpd
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin
        from shapely.geometry import box

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)

            # Toy admin polygons and AOI/bounds hash.
            admin_gdf = gpd.GeoDataFrame(
                {"iso3": ["AAA", "AAA"], "geometry": [box(0, 0, 1, 1), box(1, 0, 2, 1)]},
                crs="EPSG:4326",
            )
            filtered = filter_admin_for_iso3(admin_gdf, "AAA")
            aoi = build_admin_aoi(filtered, buffer_km=0.0, out_crs="EPSG:4326")
            h = admin_bounds_hash("AAA", aoi["admin_bounds"])
            self.assertEqual(len(h), 64)

            # Toy raster alignment.
            src_tif = td_path / "src.tif"
            ref_tif = td_path / "ref.tif"
            src_arr = np.arange(1, 17, dtype="float32").reshape(4, 4)
            write_array_geotiff(src_tif, src_arr, from_origin(0, 4, 1, 1), "EPSG:4326", nodata=-9999)
            with rasterio.open(
                ref_tif,
                "w",
                driver="GTiff",
                height=2,
                width=2,
                count=1,
                dtype="float32",
                crs="EPSG:4326",
                transform=from_origin(0, 4, 2, 2),
                nodata=-9999,
            ) as dst:
                dst.write(np.zeros((2, 2), dtype="float32"), 1)

            aligned, _ = align_to_reference(src_tif, ref_tif)
            self.assertEqual(aligned.shape, (2, 2))

            # Toy zonal aggregation on aligned raster.
            geoms = [box(0, 2, 2, 4), box(2, 0, 4, 2)]
            totals = zonal_sum(src_arr, from_origin(0, 4, 1, 1), geoms)
            self.assertEqual(len(totals), 2)
            self.assertGreater(totals[0], 0)


if __name__ == "__main__":
    unittest.main()
