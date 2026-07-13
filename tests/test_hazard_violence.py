from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from wia_pipelines.hazards.violence import (
    ViolenceRunInputs,
    acled_buffer_km,
    build_violence_run_context,
    run_violence_pipeline,
)


class ViolenceHazardTests(unittest.TestCase):
    def test_acled_buffer_km(self) -> None:
        self.assertEqual(acled_buffer_km("Battles", 0), 5)
        self.assertEqual(acled_buffer_km("Explosions/Remote violence", 0), 5)
        self.assertEqual(acled_buffer_km("Violence against civilians", 0), 2)
        self.assertEqual(acled_buffer_km("Violence against civilians", 1), 5)
        self.assertEqual(acled_buffer_km("Riots", 0), 2)
        self.assertEqual(acled_buffer_km("Protests", 0), 1)

    def test_build_violence_run_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx = build_violence_run_context(
                ViolenceRunInputs(
                    iso3="YEM",
                    as_of_date="2025-12-31",
                    lookback_months=12,
                    output_root=Path(td),
                ),
                create_dirs=True,
                write_metadata=True,
            )
            self.assertEqual(ctx["config"].hazard, "violence")
            self.assertTrue((ctx["layout"]["base"] / "run_metadata.json").exists())

    def test_run_violence_pipeline_golden_toy(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            # Tiny 4x4 WorldPop grid (EPSG:4326), 10 persons per pixel.
            wp_path = root / "toy_worldpop.tif"
            wp_data = np.full((4, 4), 10, dtype="float32")
            wp_profile = {
                "driver": "GTiff",
                "height": 4,
                "width": 4,
                "count": 1,
                "dtype": "float32",
                "crs": "EPSG:4326",
                "transform": from_origin(0, 4, 1, 1),
                "nodata": -9999.0,
            }
            with rasterio.open(wp_path, "w", **wp_profile) as dst:
                dst.write(wp_data, 1)

            # Single admin polygon covering the raster extent.
            admin_path = root / "toy_admin.gpkg"
            admin_gdf = gpd.GeoDataFrame(
                {"iso3": ["YEM"], "adm2_pcode": ["YEM001"], "geometry": [box(0, 0, 4, 4)]},
                crs="EPSG:4326",
            )
            admin_gdf.to_file(admin_path, layer="admin2", driver="GPKG")

            # Two events in two separate cells; default included types exclude protests.
            acled_path = root / "acled_yem_toy.csv"
            pd.DataFrame(
                [
                    {
                        "latitude": 3.5,
                        "longitude": 0.5,
                        "event_date": "2025-06-01",
                        "event_type": "Battles",
                        "fatalities": 0,
                    },
                    {
                        "latitude": 2.5,
                        "longitude": 1.5,
                        "event_date": "2025-06-15",
                        "event_type": "Riots",
                        "fatalities": 0,
                    },
                ]
            ).to_csv(acled_path, index=False)

            summary = run_violence_pipeline(
                inputs=ViolenceRunInputs(
                    iso3="YEM",
                    as_of_date="2025-12-31",
                    lookback_months=12,
                    output_root=root / "outputs",
                ),
                admin_path=admin_path,
                worldpop_path=wp_path,
                acled_csv=acled_path,
                admin_layer="admin2",
                included_event_types=["Battles", "Riots"],
                worldpop_coverage_min_pct=98.0,
                mask_threshold_events=1,
                all_touched=True,
            )

            run_dir = Path(summary["run_dir"])
            self.assertTrue((run_dir / "run_metadata.json").exists())
            self.assertTrue(Path(summary["outputs"]["qc_coverage_png"]).exists())
            self.assertTrue(Path(summary["outputs"]["qc_mask_png"]).exists())
            self.assertTrue(Path(summary["outputs"]["qc_mask_worldpop_png"]).exists())
            table = pd.read_csv(summary["outputs"]["adm2_stats_csv"])
            self.assertEqual(len(table), 1)
            self.assertAlmostEqual(float(table["pop_total"].iloc[0]), 160.0, places=3)
            self.assertAlmostEqual(float(table["pop_affected"].iloc[0]), 20.0, places=3)
            self.assertAlmostEqual(float(table["pop_weighted_event_count_sum"].iloc[0]), 20.0, places=3)
            self.assertAlmostEqual(float(table["pop_weighted_mean_event_count"].iloc[0]), 0.125, places=6)


if __name__ == "__main__":
    unittest.main()
