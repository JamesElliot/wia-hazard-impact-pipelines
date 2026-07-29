from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd
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
        from conftest import make_admin_gpkg, make_worldpop_tif

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            # Tiny 4x4 WorldPop grid (EPSG:4326), 10 persons per pixel.
            wp_path = make_worldpop_tif(
                root / "toy_worldpop.tif", shape=(4, 4), value=10, transform=from_origin(0, 4, 1, 1)
            )

            # Single admin polygon covering the raster extent.
            admin_path = make_admin_gpkg(
                root / "toy_admin.gpkg",
                geometries=[box(0, 0, 4, 4)],
                extra_columns={"iso3": ["YEM"], "adm2_pcode": ["YEM001"]},
                layer="admin2",
            )

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
            table = pd.read_csv(summary["outputs"]["admin_stats_csv"])
            self.assertEqual(len(table), 1)
            self.assertAlmostEqual(float(table["pop_total"].iloc[0]), 160.0, places=3)
            self.assertAlmostEqual(float(table["pop_affected"].iloc[0]), 20.0, places=3)
            self.assertAlmostEqual(float(table["pop_weighted_event_count_sum"].iloc[0]), 20.0, places=3)
            self.assertAlmostEqual(float(table["pop_weighted_mean_event_count"].iloc[0]), 0.125, places=6)
            self.assertTrue(
                {
                    "iso3",
                    "admin_level",
                    "admin_pcode",
                    "period_start",
                    "period_end",
                    "hazard",
                    "method_version",
                    "population_total",
                    "population_affected",
                    "pct_affected",
                    "hazard_data_coverage",
                    "population_data_coverage",
                }.issubset(table.columns)
            )

            # DOC-006/PROD-003: WorldPop/admin inputs are checksummed for
            # reproducibility provenance.
            import hashlib
            import json

            metadata = json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(
                metadata["inputs"]["worldpop_sha256"], hashlib.sha256(wp_path.read_bytes()).hexdigest()
            )
            self.assertEqual(metadata["inputs"]["admin_path"], str(admin_path))

    def _run_with_worldpop_row_count(self, n_rows: int):
        # Shrinks the WorldPop raster's vertical extent so it only partially covers
        # the 4x4 admin AOI, exercising the two-tier preflight-coverage gate
        # (ARCH-012) instead of the golden-toy test's full-coverage happy path.
        import json

        from conftest import make_admin_gpkg, make_worldpop_tif

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            wp_path = make_worldpop_tif(
                root / "toy_worldpop.tif", shape=(n_rows, 4), value=10, transform=from_origin(0, 4, 1, 1)
            )
            admin_path = make_admin_gpkg(
                root / "toy_admin.gpkg",
                geometries=[box(0, 0, 4, 4)],
                extra_columns={"iso3": ["YEM"], "adm2_pcode": ["YEM001"]},
                layer="admin2",
            )
            acled_path = root / "acled_yem_toy.csv"
            pd.DataFrame(
                [
                    {
                        "latitude": 3.5,
                        "longitude": 0.5,
                        "event_date": "2025-06-01",
                        "event_type": "Battles",
                        "fatalities": 0,
                    }
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
            metadata = json.loads(
                (Path(summary["run_dir"]) / "run_metadata.json").read_text(encoding="utf-8")
            )
            return summary, metadata

    def test_worldpop_coverage_between_hard_min_and_target_warns_not_fails(self) -> None:
        # 3 of 4 rows -> WorldPop raster covers y in [1, 4], 75% of the admin bbox area:
        # above the 50% hard-min, below the 98% target.
        _summary, metadata = self._run_with_worldpop_row_count(3)
        cov = metadata["preflight_coverage"]["worldpop"]["coverage_pct"]
        self.assertAlmostEqual(cov, 75.0, places=3)
        messages = [w["message"] for w in metadata.get("warnings", [])]
        self.assertTrue(any("WorldPop coverage below target threshold" in m for m in messages))

    def test_worldpop_coverage_below_hard_min_raises(self) -> None:
        # 1 of 4 rows -> WorldPop raster covers only 25% of the admin bbox area,
        # below the 50% hard minimum, so this must still hard-fail.
        with self.assertRaises(RuntimeError):
            self._run_with_worldpop_row_count(1)


if __name__ == "__main__":
    unittest.main()
