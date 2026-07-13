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


if __name__ == "__main__":
    unittest.main()
