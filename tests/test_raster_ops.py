from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from wia_pipelines.core.raster_ops import align_to_reference, write_array_geotiff

HAS_RASTER = all(importlib.util.find_spec(m) is not None for m in ("rasterio", "numpy"))


@unittest.skipUnless(HAS_RASTER, "rasterio/numpy not installed")
class RasterOpsTests(unittest.TestCase):
    def test_write_and_align(self) -> None:
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            src_tif = td_path / "src.tif"
            ref_tif = td_path / "ref.tif"

            src_arr = np.arange(16, dtype="float32").reshape(4, 4)
            ref_arr = np.zeros((2, 2), dtype="float32")
            write_array_geotiff(
                src_tif,
                src_arr,
                from_origin(0, 4, 1, 1),
                "EPSG:4326",
                nodata=-9999,
                dtype="float32",
            )
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
                dst.write(ref_arr, 1)

            aligned, profile = align_to_reference(src_tif, ref_tif)
            self.assertEqual(aligned.shape, (2, 2))
            self.assertEqual(profile["width"], 2)

    def test_align_to_reference_reprojects_across_different_crs(self) -> None:
        # Source raster in Web Mercator (EPSG:3857) covering the same real-world
        # extent as an EPSG:4326 reference (lon/lat 0..1). If the CRS transform
        # were skipped or wrong, the aligned output would be nodata/misaligned
        # instead of carrying the source's uniform fill value through.
        import numpy as np
        import rasterio
        from pyproj import Transformer
        from rasterio.transform import from_origin

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            src_tif = td_path / "src_3857.tif"
            ref_tif = td_path / "ref_4326.tif"

            to_3857 = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
            x0, y0 = to_3857.transform(0, 0)
            x1, y1 = to_3857.transform(1, 1)

            src_arr = np.full((10, 10), 5.0, dtype="float32")
            write_array_geotiff(
                src_tif,
                src_arr,
                from_origin(x0, y1, (x1 - x0) / 10, (y1 - y0) / 10),
                "EPSG:3857",
                nodata=-9999,
                dtype="float32",
            )
            with rasterio.open(
                ref_tif,
                "w",
                driver="GTiff",
                height=4,
                width=4,
                count=1,
                dtype="float32",
                crs="EPSG:4326",
                transform=from_origin(0, 1, 0.25, 0.25),
                nodata=-9999,
            ) as dst:
                dst.write(np.zeros((4, 4), dtype="float32"), 1)

            aligned, profile = align_to_reference(src_tif, ref_tif)
            self.assertEqual(aligned.shape, (4, 4))
            self.assertEqual(profile["crs"].to_string(), "EPSG:4326")
            # Every output pixel falls within the source's real-world extent,
            # so a correct reprojection carries the fill value through everywhere.
            self.assertTrue(np.all(aligned == 5.0))


if __name__ == "__main__":
    unittest.main()
