from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

from wia_pipelines.hazards.utci import (
    UtciPipelineRunOptions,
    UtciRunInputs,
    _consecutive_k_exceedance,
    _exceeds_threshold,
    _find_daily_stat_utci,
    _threshold_key,
    build_utci_run_context,
    run_utci_pipeline,
)

HAS_XARRAY = importlib.util.find_spec("xarray") is not None
HAS_GEO = all(
    importlib.util.find_spec(m) is not None
    for m in ("geopandas", "rasterio", "shapely", "pyproj", "fiona", "numpy", "xarray")
)


class UtciHazardTests(unittest.TestCase):
    def test_build_utci_run_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx = build_utci_run_context(
                UtciRunInputs(
                    iso3="MLI",
                    as_of_date="2025-12-31",
                    lookback_months=12,
                    output_root=Path(td),
                ),
                create_dirs=True,
                write_metadata=True,
            )
            self.assertEqual(ctx["config"].hazard, "heat")
            self.assertTrue((ctx["layout"]["base"] / "run_metadata.json").exists())

    def test_build_utci_run_context_cold(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx = build_utci_run_context(
                UtciRunInputs(iso3="AFG", as_of_date="2026-06-30", output_root=Path(td), extreme="cold"),
                create_dirs=True,
                write_metadata=True,
            )
            self.assertEqual(ctx["config"].hazard, "cold")
            self.assertEqual(ctx["metadata"]["run_id"], "AFG_2025-07-01_2026-06-30_m12_cold")
            self.assertEqual(ctx["metadata"]["pipeline"], "extreme_cold_utci")
            self.assertIn("/cold", str(ctx["layout"]["base"]))

    def test_invalid_extreme_rejected(self) -> None:
        with self.assertRaises(ValueError):
            UtciRunInputs(iso3="AFG", as_of_date="2026-06-30", extreme="hot")

    def test_threshold_keys(self) -> None:
        self.assertEqual(_threshold_key("heat", 38.0), "abs_38c")
        self.assertEqual(_threshold_key("cold", -13.0), "cold_m13c")
        self.assertEqual(_threshold_key("cold", 0.0), "cold_0c")

    def test_cold_with_heat_default_thresholds_is_rejected(self) -> None:
        opts = UtciPipelineRunOptions(
            inputs=UtciRunInputs(iso3="AFG", as_of_date="2026-06-30", extreme="cold"),
            admin_path=Path("x"),
            worldpop_path=Path("y"),
        )
        with self.assertRaisesRegex(ValueError, "explicit cold thresholds"):
            run_utci_pipeline(opts)

    def test_default_reporting_threshold_is_explicit(self) -> None:
        fields = UtciPipelineRunOptions.__dataclass_fields__
        self.assertEqual(fields["default_reporting_threshold_c"].default, 32.0)


@unittest.skipUnless(HAS_XARRAY, "xarray not installed")
class ConsecutiveKExceedanceTests(unittest.TestCase):
    def _exceed_da(self, values):
        import numpy as np
        import xarray as xr

        return xr.DataArray(np.array(values, dtype=bool), dims=("time", "cell"))

    def test_three_consecutive_days_triggers_exceedance(self) -> None:
        # Cell 0: days 2-4 exceed (3 in a row) -> should trigger for k=3.
        da = self._exceed_da(
            [[False], [True], [True], [True], [False]],
        )
        result = _consecutive_k_exceedance(da, k=3)
        self.assertTrue(bool(result.values[0]))

    def test_two_consecutive_days_does_not_trigger_k_three(self) -> None:
        da = self._exceed_da(
            [[False], [True], [True], [False], [False]],
        )
        result = _consecutive_k_exceedance(da, k=3)
        self.assertFalse(bool(result.values[0]))

    def test_non_consecutive_days_do_not_trigger(self) -> None:
        # Three total exceedance days, but never 3 in a row.
        da = self._exceed_da(
            [[True], [False], [True], [False], [True]],
        )
        result = _consecutive_k_exceedance(da, k=3)
        self.assertFalse(bool(result.values[0]))

    def test_k_one_is_any_single_day_exceedance(self) -> None:
        da = self._exceed_da([[False], [False], [True], [False]])
        result = _consecutive_k_exceedance(da, k=1)
        self.assertTrue(bool(result.values[0]))

    def test_shorter_series_than_k_never_triggers(self) -> None:
        da = self._exceed_da([[True], [True]])
        result = _consecutive_k_exceedance(da, k=3)
        self.assertFalse(bool(result.values[0]))

    def test_independent_per_cell(self) -> None:
        # cell 0 has a 3-day run, cell 1 does not.
        da = self._exceed_da(
            [[True, True], [True, False], [True, True], [False, False]],
        )
        result = _consecutive_k_exceedance(da, k=3)
        self.assertTrue(bool(result.values[0]))
        self.assertFalse(bool(result.values[1]))


@unittest.skipUnless(HAS_GEO, "geospatial stack not installed")
class UtciPipelineExecutionTests(unittest.TestCase):
    def test_run_utci_pipeline_golden_toy(self) -> None:
        # End-to-end run_utci_pipeline execution with no real CDS access:
        # download_cds is monkeypatched to synthesize a small daily-max-UTCI
        # NetCDF covering the AOI instead of calling the live API. Every day
        # of the window is set well above all three thresholds, so the whole
        # admin unit should read 100% affected for the default (k=3) rule --
        # a hand-computable golden case, mirroring test_hazard_spei.py's.
        import zipfile
        from unittest.mock import patch

        import numpy as np
        import pandas as pd
        import xarray as xr
        from rasterio.transform import from_origin
        from shapely.geometry import box

        import wia_pipelines.core.cds as core_cds
        import wia_pipelines.hazards.coverage_checks as coverage_checks
        from conftest import make_admin_gpkg, make_worldpop_tif
        from wia_pipelines.hazards.utci import UtciPipelineRunOptions, run_utci_pipeline

        def fake_download_cds(dataset, request, out_zip):
            year = int(request["year"][0])
            month = int(request["month"][0])
            days = pd.date_range(f"{year:04d}-{month:02d}-01", periods=len(request["day"]), freq="D")
            nc_path = out_zip.parent / f"{out_zip.stem}.nc"
            nc_path.parent.mkdir(parents=True, exist_ok=True)
            ds = xr.Dataset(
                {
                    "utci_max": (
                        ("time", "lat", "lon"),
                        np.full((len(days), 7, 7), 50.0, dtype="float32"),
                    )
                },
                coords={
                    "time": days.values,
                    "lat": np.linspace(2.0, -1.0, 7),
                    "lon": np.linspace(-1.0, 2.0, 7),
                },
            )
            ds.to_netcdf(nc_path)
            with zipfile.ZipFile(out_zip, "w") as zf:
                zf.write(nc_path, arcname=nc_path.name)
            return True, None

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            admin_path = make_admin_gpkg(
                root / "admin.gpkg",
                geometries=[box(0, 0, 1, 1)],
                extra_columns={"iso3": ["AAA"], "adm_level": [2], "adm2_pcode": ["AAA001"]},
                layer="admin2",
            )
            worldpop_path = make_worldpop_tif(
                root / "worldpop.tif", shape=(10, 10), value=10.0, transform=from_origin(0, 1, 0.1, 0.1)
            )

            with (
                patch.object(core_cds, "download_cds", side_effect=fake_download_cds),
                patch.object(coverage_checks, "download_cds", side_effect=fake_download_cds),
            ):
                summary = run_utci_pipeline(
                    UtciPipelineRunOptions(
                        inputs=self._utci_inputs(root),
                        admin_path=admin_path,
                        worldpop_path=worldpop_path,
                        admin_layer="admin2",
                        iso3_field="iso3",
                    )
                )

            table = pd.read_csv(summary["outputs"]["admin_table"])
            row = table.iloc[0]
            self.assertEqual(row["adm2_pcode"], "AAA001")
            self.assertAlmostEqual(row["population_total"], 1000.0, places=3)
            self.assertAlmostEqual(row["pct_affected"], 100.0, places=3)

            # DOC-006/PROD-003: WorldPop/admin inputs are checksummed for
            # reproducibility provenance.
            import hashlib
            import json as json_module

            metadata = json_module.loads(Path(summary["metadata_path"]).read_text(encoding="utf-8"))
            self.assertEqual(
                metadata["inputs"]["worldpop"]["sha256"],
                hashlib.sha256(worldpop_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(metadata["inputs"]["admin"]["path"], str(admin_path.resolve()))
            self.assertEqual(metadata["admin_source"]["vintage"], "TEST2026-01")

    @staticmethod
    def _utci_inputs(root: Path):
        return UtciRunInputs(
            iso3="AAA",
            as_of_date="2025-01-31",
            lookback_months=1,
            output_root=root / "outputs",
            target_adm_level=2,
        )


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(HAS_XARRAY, "xarray not installed")
class ColdDirectionTests(unittest.TestCase):
    def test_exceeds_threshold_is_strict_and_directional(self) -> None:
        import numpy as np
        import xarray as xr

        da = xr.DataArray(np.array([-12.9, -13.0, -13.1, np.nan]), dims=("time",))
        cold = _exceeds_threshold(da, -13.0, "cold").values.tolist()
        self.assertEqual(cold, [False, False, True, False])  # strict <, NaN is not cold
        heat = _exceeds_threshold(da, -13.0, "heat").values.tolist()
        self.assertEqual(heat, [True, False, False, False])

    def test_cold_run_of_three_days(self) -> None:
        import numpy as np
        import xarray as xr

        tmin = xr.DataArray(np.array([[-20.0], [-20.0], [-5.0], [-20.0], [-20.0]]), dims=("time", "cell"))
        mask = _consecutive_k_exceedance(_exceeds_threshold(tmin, -13.0, "cold"), k=3)
        self.assertFalse(bool(mask.values[0]))  # the warm day breaks both runs of two
        tmin2 = tmin.copy(data=np.array([[-20.0], [-20.0], [-20.0], [-5.0], [-5.0]]))
        self.assertTrue(
            bool(_consecutive_k_exceedance(_exceeds_threshold(tmin2, -13.0, "cold"), k=3).values[0])
        )

    def test_find_daily_stat_selects_min_and_max(self) -> None:
        import numpy as np
        import xarray as xr

        ds = xr.Dataset(
            {
                "utci_daily_min": (("time",), np.array([250.0])),
                "utci_daily_max": (("time",), np.array([280.0])),
                "time_bnds": (("time",), np.array([0.0])),
            }
        )
        self.assertEqual(float(_find_daily_stat_utci(ds, "min").values[0]), 250.0)
        self.assertEqual(float(_find_daily_stat_utci(ds, "max").values[0]), 280.0)
