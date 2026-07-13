from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from wia_pipelines.hazards.coverage_checks import (
    days_for_year_month,
    prepare_country_admin_context,
    spei_sample_request,
    utci_sample_request,
)

HAS_GEO = all(importlib.util.find_spec(m) is not None for m in ("geopandas", "shapely", "fiona", "pyproj"))


class CoverageChecksTests(unittest.TestCase):
    def test_days_for_year_month_handles_leap(self) -> None:
        feb_2024 = days_for_year_month(2024, 2)
        feb_2025 = days_for_year_month(2025, 2)
        self.assertEqual(len(feb_2024), 29)
        self.assertEqual(len(feb_2025), 28)
        self.assertEqual(feb_2024[0], "01")
        self.assertEqual(feb_2024[-1], "29")

    def test_spei_request_shape(self) -> None:
        req = spei_sample_request(2025, 1, [35.0, 34.0, 33.0, 36.0])
        self.assertEqual(req["dataset_type"], "consolidated_dataset")
        self.assertEqual(req["year"], ["2025"])
        self.assertEqual(req["month"], ["01"])
        self.assertIn("standardised_precipitation_evapotranspiration_index", req["variable"])

    def test_utci_request_shape(self) -> None:
        req = utci_sample_request(2025, 1, [35.0, 34.0, 33.0, 36.0])
        self.assertEqual(req["product_type"], "consolidated_dataset")
        self.assertEqual(req["year"], ["2025"])
        self.assertEqual(req["month"], ["01"])
        self.assertEqual(req["day"][0], "01")
        self.assertEqual(req["day"][-1], "31")
        self.assertIn("universal_thermal_climate_index_daily_statistics", req["variable"])

    @unittest.skipUnless(HAS_GEO, "geospatial stack not installed")
    def test_prepare_country_admin_context_applies_cds_buffer(self) -> None:
        import geopandas as gpd
        from shapely.geometry import box

        with tempfile.TemporaryDirectory() as td:
            gpkg = Path(td) / "admin.gpkg"
            gdf = gpd.GeoDataFrame(
                {"iso3": ["AAA"], "geometry": [box(10, 20, 11, 21)]},
                crs="EPSG:4326",
            )
            gdf.to_file(gpkg, layer="admin2", driver="GPKG")
            ctx = prepare_country_admin_context(
                iso3="AAA",
                admin_path=gpkg,
                admin_layer="admin2",
                iso3_field="iso3",
                cds_buffer_deg=0.25,
            )
            w, s, e, n = ctx["admin_bounds_wsen"]
            bw, bs, be, bn = ctx["cds_bounds_wsen"]
            self.assertAlmostEqual(bw, w - 0.25, places=6)
            self.assertAlmostEqual(bs, s - 0.25, places=6)
            self.assertAlmostEqual(be, e + 0.25, places=6)
            self.assertAlmostEqual(bn, n + 0.25, places=6)


if __name__ == "__main__":
    unittest.main()
