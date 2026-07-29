from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np

from wia_pipelines.hazards.hydrodrought import (
    HydrodroughtRunInputs,
    PERSISTENCE_MONTHS,
    _find_discharge_var,
    _persistent_occurrence,
    build_hydrodrought_run_context,
    hydrodrought_month_window,
    prepare_hydrodrought_geography,
)

HAS_GEO = all(
    importlib.util.find_spec(m) is not None
    for m in ("geopandas", "rasterio", "shapely", "pyproj", "fiona", "numpy")
)


class HydrodroughtWindowTests(unittest.TestCase):
    def test_month_window_includes_accumulation_lead_in(self) -> None:
        window = hydrodrought_month_window("2025-12-31", lookback_months=3, accumulation_months=3)
        self.assertEqual(
            window["months_for_accumulation"],
            [(2025, 8), (2025, 9), (2025, 10), (2025, 11), (2025, 12)],
        )
        self.assertEqual(window["reported_months"], [(2025, 10), (2025, 11), (2025, 12)])
        self.assertEqual(window["start_yyyy_mm"], "2025-10")
        self.assertEqual(window["end_yyyy_mm"], "2025-12")

    def test_accumulation_one_needs_no_lead_in(self) -> None:
        window = hydrodrought_month_window("2025-12-31", lookback_months=2, accumulation_months=1)
        self.assertEqual(window["months_for_accumulation"], window["reported_months"])

    def test_build_run_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx = build_hydrodrought_run_context(
                HydrodroughtRunInputs(
                    iso3="SOM",
                    as_of_date="2025-12-31",
                    output_root=Path(td) / "outputs",
                ),
                create_dirs=True,
                write_metadata=True,
            )
            self.assertTrue(ctx["layout"]["base"].exists())
            self.assertTrue(ctx["metadata_path"].exists())
            self.assertEqual(ctx["metadata"]["run_config"]["hazard"], "hydrodrought")
            self.assertEqual(ctx["layout"]["base"].name, "hydrodrought")
            self.assertEqual(ctx["layout"]["base"].parent.parent.name, "SOM")


class DischargeVarTests(unittest.TestCase):
    def test_find_discharge_var_prefers_dis24(self) -> None:
        import xarray as xr

        ds = xr.Dataset(
            data_vars={
                "crs": xr.DataArray(0),
                "dis24": xr.DataArray(np.zeros((2, 3, 4), dtype="float32"), dims=("time", "lat", "lon")),
            }
        )
        self.assertEqual(_find_discharge_var(ds), "dis24")

    def test_find_discharge_var_falls_back_to_any_spatial_time_var(self) -> None:
        import xarray as xr

        ds = xr.Dataset(
            data_vars={
                "some_other_name": xr.DataArray(
                    np.zeros((2, 3, 4), dtype="float32"), dims=("time", "lat", "lon")
                ),
            }
        )
        self.assertEqual(_find_discharge_var(ds), "some_other_name")

    def test_find_discharge_var_raises_without_spatial_time_dims(self) -> None:
        import xarray as xr

        ds = xr.Dataset(data_vars={"scalar": xr.DataArray(1.0)})
        with self.assertRaises(KeyError):
            _find_discharge_var(ds)


class PersistentOccurrenceTests(unittest.TestCase):
    def test_persistence_requires_consecutive_months(self) -> None:
        # 4 months x 1 cell: below-threshold in months 0,2,3 but not 1 -> only
        # months (2,3) form a consecutive run of length 2.
        below = np.array([[True], [False], [True], [True]])
        result = _persistent_occurrence(below, min_consecutive=PERSISTENCE_MONTHS)
        self.assertTrue(result[0])

    def test_no_persistent_run_returns_false(self) -> None:
        below = np.array([[True], [False], [True], [False]])
        result = _persistent_occurrence(below, min_consecutive=2)
        self.assertFalse(result[0])

    def test_min_consecutive_one_is_any_occurrence(self) -> None:
        below = np.array([[False], [False], [True], [False]])
        result = _persistent_occurrence(below, min_consecutive=1)
        self.assertTrue(result[0])

    def test_shorter_series_than_window_returns_false(self) -> None:
        below = np.array([[True]])
        result = _persistent_occurrence(below, min_consecutive=2)
        self.assertFalse(result[0])


@unittest.skipUnless(HAS_GEO, "geospatial stack not installed")
class HydrodroughtGeographyTests(unittest.TestCase):
    def test_prepare_hydrodrought_geography(self) -> None:
        from rasterio.transform import from_origin
        from shapely.geometry import box

        from conftest import make_admin_gpkg, make_worldpop_tif

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            gpkg = make_admin_gpkg(
                td_path / "admin.gpkg",
                geometries=[box(0, 0, 1, 1), box(1, 0, 2, 1), box(10, 10, 11, 11)],
                extra_columns={"iso3": ["AAA", "AAA", "BBB"], "adm_level": [2, 2, 2]},
                layer="admin2",
            )
            worldpop_tif = make_worldpop_tif(
                td_path / "wp.tif", shape=(4, 4), transform=from_origin(0, 2, 0.5, 0.5)
            )

            out = prepare_hydrodrought_geography(
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
