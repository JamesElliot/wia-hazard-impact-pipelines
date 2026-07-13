from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np
import xarray as xr

from wia_pipelines.hazards.spei import (
    SpeiRunInputs,
    _find_spei_var,
    build_spei_run_context,
    prepare_spei_geography,
    spei_month_window,
)

HAS_GEO = all(
    importlib.util.find_spec(m) is not None
    for m in ("geopandas", "rasterio", "shapely", "pyproj", "fiona", "numpy")
)


class SpeiWindowTests(unittest.TestCase):
    def test_month_window(self) -> None:
        window = spei_month_window("2025-12-31", lookback_months=3)
        self.assertEqual(window["months"], [(2025, 10), (2025, 11), (2025, 12)])
        self.assertEqual(window["start_yyyy_mm"], "2025-10")
        self.assertEqual(window["end_yyyy_mm"], "2025-12")

    def test_build_run_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx = build_spei_run_context(
                SpeiRunInputs(
                    iso3="MLI",
                    as_of_date="2025-12-31",
                    output_root=Path(td) / "outputs",
                ),
                create_dirs=True,
                write_metadata=True,
            )
            self.assertTrue(ctx["layout"]["base"].exists())
            self.assertTrue(ctx["metadata_path"].exists())
            self.assertEqual(ctx["metadata"]["run_config"]["hazard"], "drought")

    def test_find_spei_var_ignores_non_spatial_preferred_name(self) -> None:
        ds = xr.Dataset(
            data_vars={
                "SPEI3": xr.DataArray(np.array([0.0, 1.0]), dims=("bnds",)),
                "spei3_main": xr.DataArray(
                    np.zeros((1, 2, 3), dtype="float32"),
                    dims=("time", "lat", "lon"),
                ),
            }
        )
        self.assertEqual(_find_spei_var(ds), "spei3_main")


@unittest.skipUnless(HAS_GEO, "geospatial stack not installed")
class SpeiGeographyTests(unittest.TestCase):
    def test_prepare_spei_geography(self) -> None:
        import geopandas as gpd
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin
        from shapely.geometry import box

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            gpkg = td_path / "admin.gpkg"
            worldpop_tif = td_path / "wp.tif"

            gdf = gpd.GeoDataFrame(
                {
                    "iso3": ["AAA", "AAA", "BBB"],
                    "adm_level": [2, 2, 2],
                    "geometry": [box(0, 0, 1, 1), box(1, 0, 2, 1), box(10, 10, 11, 11)],
                },
                crs="EPSG:4326",
            )
            gdf.to_file(gpkg, layer="admin2", driver="GPKG")

            arr = np.ones((4, 4), dtype="float32")
            with rasterio.open(
                worldpop_tif,
                "w",
                driver="GTiff",
                height=4,
                width=4,
                count=1,
                dtype="float32",
                crs="EPSG:4326",
                transform=from_origin(0, 2, 0.5, 0.5),
                nodata=-9999,
            ) as dst:
                dst.write(arr, 1)

            out = prepare_spei_geography(
                iso3="AAA",
                admin_path=gpkg,
                admin_layer="admin2",
                iso3_field="iso3",
                adm_level_field="adm_level",
                target_adm_level=2,
                worldpop_path=worldpop_tif,
            )
            self.assertIn("aoi", out)
            self.assertEqual(len(out["bounds_hash"]), 64)
            self.assertIsNotNone(out["overlap_report"])


if __name__ == "__main__":
    unittest.main()
