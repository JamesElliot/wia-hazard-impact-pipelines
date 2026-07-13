from __future__ import annotations

import unittest

import numpy as np


class FloodDaysLogicTests(unittest.TestCase):
    def test_days_sum_and_binary_threshold(self) -> None:
        # toy stack: time,y,x
        arr = np.array(
            [
                [[0, 1], [255, 2]],
                [[1, 0], [255, 2]],
                [[0, 3], [0, 255]],
            ],
            dtype=np.uint8,
        )
        nodata = 255

        flooded = (arr != nodata) & (arr > 0)
        flood_days = flooded.sum(axis=0).astype(np.uint16)

        expected_days = np.array([[1, 2], [0, 2]], dtype=np.uint16)
        np.testing.assert_array_equal(flood_days, expected_days)

        binary_gt0 = (flood_days > 0).astype(np.uint8)
        expected_gt0 = np.array([[1, 1], [0, 1]], dtype=np.uint8)
        np.testing.assert_array_equal(binary_gt0, expected_gt0)

        binary_gt1 = (flood_days > 1).astype(np.uint8)
        expected_gt1 = np.array([[0, 1], [0, 1]], dtype=np.uint8)
        np.testing.assert_array_equal(binary_gt1, expected_gt1)


if __name__ == "__main__":
    unittest.main()
