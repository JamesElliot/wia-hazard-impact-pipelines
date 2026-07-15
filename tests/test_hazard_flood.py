from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from wia_pipelines.hazards.flood import (
    FloodRunInputs,
    build_flood_run_context,
    evaluate_preflight_coverage,
    flood_binary_from_days,
    group_stac_items_by_day,
    make_progress_writer,
)


class FloodHazardTests(unittest.TestCase):
    def test_group_stac_items_by_day(self) -> None:
        class Item:
            def __init__(self, item_id: str, timestamp: str) -> None:
                self.id = item_id
                self.properties = {"datetime": timestamp}

        grouped = group_stac_items_by_day(
            [
                Item("b", "2025-01-02T18:00:00Z"),
                Item("a", "2025-01-01T06:00:00Z"),
                Item("c", "2025-01-02T05:00:00Z"),
            ]
        )
        self.assertEqual(list(grouped), ["2025-01-01", "2025-01-02"])
        self.assertEqual([item.id for item in grouped["2025-01-02"]], ["b", "c"])

    def test_build_flood_run_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            ctx = build_flood_run_context(
                FloodRunInputs(
                    iso3="MLI",
                    as_of_date="2025-12-31",
                    lookback_months=12,
                    output_root=Path(td),
                ),
                create_dirs=True,
                write_metadata=True,
            )
            self.assertEqual(ctx["config"].hazard, "flood")
            self.assertTrue((ctx["layout"]["base"] / "run_metadata.json").exists())

    def test_flood_binary_from_days(self) -> None:
        days = np.array([[0, 1, 4], [7, 0, 2]], dtype=np.uint16)
        out = flood_binary_from_days(days, threshold_days=0)
        exp = np.array([[0, 1, 1], [1, 0, 1]], dtype=np.uint8)
        np.testing.assert_array_equal(out, exp)

        out2 = flood_binary_from_days(days, threshold_days=3)
        exp2 = np.array([[0, 0, 1], [1, 0, 0]], dtype=np.uint8)
        np.testing.assert_array_equal(out2, exp2)

    def test_evaluate_preflight_coverage(self) -> None:
        report = evaluate_preflight_coverage(99.0, 100.0, worldpop_min_pct=98.0, flood_min_pct=99.999)
        self.assertTrue(report["worldpop_ok"])
        self.assertTrue(report["flood_stac_ok"])
        self.assertTrue(report["ok"])

    def test_make_progress_writer(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            status_path = Path(td) / "status.json"
            writer = make_progress_writer(status_path, stage="test", total=10)
            payload = writer(processed=3, ok=2, failed=1, current="chunk-1")
            self.assertTrue(status_path.exists())
            on_disk = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["stage"], "test")
            self.assertEqual(on_disk["processed"], 3)
            self.assertEqual(payload["current"], "chunk-1")


if __name__ == "__main__":
    unittest.main()
