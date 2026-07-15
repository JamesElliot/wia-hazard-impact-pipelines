from __future__ import annotations

import importlib.util
import unittest

from wia_pipelines.core.aggregation import labelled_sum, zonal_sum

HAS_AGG = all(importlib.util.find_spec(m) is not None for m in ("rasterio", "numpy", "shapely"))


@unittest.skipUnless(HAS_AGG, "aggregation dependencies not installed")
class AggregationTests(unittest.TestCase):
    def test_labelled_sum_applies_shared_validity_mask(self) -> None:
        import numpy as np

        labels = np.array([[1, 1, 2], [1, 2, 0]], dtype="int16")
        values = np.array([[1.0, 2.0, 3.0], [4.0, np.nan, 99.0]])
        valid = np.array([[True, False, True], [True, True, True]])
        self.assertEqual(labelled_sum(labels, values, n_labels=2, valid_mask=valid), [5.0, 3.0])

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
