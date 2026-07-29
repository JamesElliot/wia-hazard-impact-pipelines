from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from wia_pipelines.core.progress import make_progress_writer


class ProgressWriterTests(unittest.TestCase):
    def test_writes_expected_payload_shape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            status_path = Path(td) / "status.json"
            writer = make_progress_writer(status_path, stage="test", total=10)
            payload = writer(processed=3, ok=2, failed=1, current="chunk-1")
            self.assertTrue(status_path.exists())
            on_disk = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk, payload)
            self.assertEqual(on_disk["stage"], "test")
            self.assertEqual(on_disk["processed"], 3)
            self.assertEqual(on_disk["total"], 10)
            self.assertEqual(on_disk["ok"], 2)
            self.assertEqual(on_disk["failed"], 1)
            self.assertEqual(on_disk["current"], "chunk-1")
            self.assertAlmostEqual(on_disk["pct_complete"], 30.0)

    def test_ok_and_failed_default_to_zero_when_omitted(self) -> None:
        # Mirrors spei.py/utci.py's raster-compute stage, which never tracks
        # per-item ok/failed counts -- only processed/total/current.
        with tempfile.TemporaryDirectory() as td:
            status_path = Path(td) / "raster_status.json"
            writer = make_progress_writer(status_path, stage="raster_compute", total=3)
            writer(0, current=None)
            payload = writer(1, current="threshold_a")
            self.assertEqual(payload["ok"], 0)
            self.assertEqual(payload["failed"], 0)
            self.assertEqual(payload["current"], "threshold_a")

    def test_zero_total_reports_full_completion(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            status_path = Path(td) / "status.json"
            writer = make_progress_writer(status_path, stage="empty", total=0)
            payload = writer(0)
            self.assertEqual(payload["total"], 0)
            self.assertEqual(payload["pct_complete"], 100.0)

    def test_constructing_a_new_writer_for_the_same_path_switches_stage(self) -> None:
        # Mirrors spei.py's download->extract sequence, which reconstructs a
        # writer per stage but reuses the same status file path.
        with tempfile.TemporaryDirectory() as td:
            status_path = Path(td) / "status.json"
            download_writer = make_progress_writer(status_path, "downloads", total=2)
            download_writer(2, ok=2, failed=0, current="2025-02")
            extract_writer = make_progress_writer(status_path, "extract", total=1)
            extract_writer(1, ok=1, failed=0, current="foo.nc")
            on_disk = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["stage"], "extract")
            self.assertEqual(on_disk["total"], 1)


if __name__ == "__main__":
    unittest.main()
