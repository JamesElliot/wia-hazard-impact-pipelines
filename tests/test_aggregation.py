from __future__ import annotations

import importlib.util
import unittest

from wia_pipelines.core.aggregation import zonal_sum

HAS_AGG = all(importlib.util.find_spec(m) is not None for m in ("rasterio", "numpy", "shapely"))


@unittest.skipUnless(HAS_AGG, "aggregation dependencies not installed")
class AggregationTests(unittest.TestCase):
    def test_zonal_sum(self) -> None:
        import numpy as np
        from rasterio.transform import from_origin
        from shapely.geometry import box

        arr = np.array(
            [
                [1, 2, 3, 4],
                [5, 6, 7, 8],
                [9, 10, 11, 12],
                [13, 14, 15, 16],
            ],
            dtype="float32",
        )
        transform = from_origin(0, 4, 1, 1)
        geoms = [box(0, 2, 2, 4), box(2, 0, 4, 2)]
        totals = zonal_sum(arr, transform, geoms, nodata=None)
        self.assertEqual(len(totals), 2)
        self.assertAlmostEqual(totals[0], 14.0)
        self.assertAlmostEqual(totals[1], 54.0)


if __name__ == "__main__":
    unittest.main()
