from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from wia_pipelines.core.worldpop import (
    bbox_coverage_report,
    worldpop_profile_and_bounds,
    worldpop_valid_mask,
)

HAS_RASTER = all(importlib.util.find_spec(m) is not None for m in ("rasterio", "numpy"))
HAS_FULL = HAS_RASTER and importlib.util.find_spec("geopandas") is not None


@unittest.skipUnless(HAS_FULL, "raster/geospatial stack not installed")
class WorldPopTests(unittest.TestCase):
    def test_profile_bounds_and_mask(self) -> None:
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin

        with tempfile.TemporaryDirectory() as td:
            tif = Path(td) / "wp.tif"
            arr = np.array([[1, 2], [3, -9999]], dtype="float32")
            with rasterio.open(
                tif,
                "w",
                driver="GTiff",
                height=2,
                width=2,
                count=1,
                dtype="float32",
                crs="EPSG:4326",
                transform=from_origin(0, 2, 1, 1),
                nodata=-9999,
            ) as dst:
                dst.write(arr, 1)

            info = worldpop_profile_and_bounds(tif)
            self.assertIn("bounds_4326", info)
            mask, _ = worldpop_valid_mask(tif)
            self.assertEqual(mask.sum(), 3)

    def test_bbox_coverage_report(self) -> None:
        report = bbox_coverage_report((0, 0, 2, 2), (0, 0, 1, 2))
        self.assertLess(report["coverage_pct"], 100.0)
        self.assertFalse(report["full_coverage"])


if __name__ == "__main__":
    unittest.main()
