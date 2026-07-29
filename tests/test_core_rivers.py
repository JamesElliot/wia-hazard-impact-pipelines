from __future__ import annotations

import importlib.util
import unittest

HAS_GEO = all(
    importlib.util.find_spec(m) is not None for m in ("geopandas", "rasterio", "shapely", "scipy", "numpy")
)


@unittest.skipUnless(HAS_GEO, "geospatial stack not installed")
class RiverCorridorTests(unittest.TestCase):
    def setUp(self) -> None:
        import geopandas as gpd
        from affine import Affine
        from shapely.geometry import LineString

        # A 10x10 grid at 1-degree resolution spanning lon/lat [0, 10],
        # origin at (0, 10), north-up.
        self.transform = Affine(1.0, 0.0, 0.0, 0.0, -1.0, 10.0)
        self.out_shape = (10, 10)

        # Two parallel north-south reaches, each running through the interior
        # of one pixel column (avoids rasterizing exactly on a pixel edge).
        reach_a = LineString([(2.5, 10.0), (2.5, 0.0)])
        reach_b = LineString([(7.5, 10.0), (7.5, 0.0)])
        self.reaches = gpd.GeoDataFrame({"ORD_STRA": [1, 3]}, geometry=[reach_a, reach_b], crs="EPSG:4326")

    def test_corridor_widths_flat_default(self) -> None:
        from wia_pipelines.core.rivers import corridor_widths_km

        widths = corridor_widths_km(self.reaches, base_width_km=5.0, per_order_km=0.0)
        self.assertEqual(list(widths), [5.0, 5.0])

    def test_corridor_widths_scale_with_strahler_order(self) -> None:
        from wia_pipelines.core.rivers import corridor_widths_km

        widths = corridor_widths_km(self.reaches, base_width_km=5.0, per_order_km=2.0)
        self.assertAlmostEqual(widths[0], 5.0)  # order 1 -> no extra width
        self.assertAlmostEqual(widths[1], 9.0)  # order 3 -> +2km per order above 1

    def test_pixel_near_reach_a_is_assigned_to_reach_a(self) -> None:
        from wia_pipelines.core.rivers import compute_river_corridor

        result = compute_river_corridor(self.reaches, self.out_shape, self.transform, base_width_km=20.0)
        # Column 2 in the 10x10 grid corresponds to lon ~2.0-2.1, right on reach_a.
        self.assertEqual(result["nearest_reach_index"][5, 2], 0)
        self.assertTrue(result["mask"][5, 2])

    def test_pixel_near_reach_b_is_assigned_to_reach_b(self) -> None:
        from wia_pipelines.core.rivers import compute_river_corridor

        result = compute_river_corridor(self.reaches, self.out_shape, self.transform, base_width_km=20.0)
        self.assertEqual(result["nearest_reach_index"][5, 7], 1)
        self.assertTrue(result["mask"][5, 7])

    def test_pixel_far_from_every_reach_is_excluded_by_narrow_corridor(self) -> None:
        from wia_pipelines.core.rivers import compute_river_corridor

        result = compute_river_corridor(self.reaches, self.out_shape, self.transform, base_width_km=1.0)
        # Column 4-5 sits roughly midway between the two reaches (~275 km away
        # from each at 0.1deg spacing), well outside a 1km corridor.
        self.assertFalse(result["mask"][5, 4])

    def test_no_reaches_produces_empty_mask(self) -> None:
        import geopandas as gpd

        from wia_pipelines.core.rivers import compute_river_corridor

        empty_reaches = gpd.GeoDataFrame({"ORD_STRA": []}, geometry=[], crs="EPSG:4326")
        result = compute_river_corridor(empty_reaches, self.out_shape, self.transform)
        self.assertFalse(result["mask"].any())
        self.assertTrue((result["nearest_reach_index"] == -1).all())


if __name__ == "__main__":
    unittest.main()
