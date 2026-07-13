from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from wia_pipelines.batch.worldpop_download import (
    build_worldpop_download_plan,
    build_worldpop_filename,
    build_worldpop_url,
)


class BatchWorldPopDownloadTests(unittest.TestCase):
    def test_build_worldpop_url_matches_schema(self) -> None:
        url = build_worldpop_url("PAK", year=2025, release="R2025A", version="v1", resolution="100m")
        self.assertEqual(
            url,
            "https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2025/PAK/v1/100m/constrained/pak_pop_2025_CN_100m_R2025A_v1.tif",
        )

    def test_build_download_plan_deduplicates_isos(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tasks = pd.DataFrame(
                [
                    {"iso3": "YEM", "is_valid_manifest": True},
                    {"iso3": "YEM", "is_valid_manifest": True},
                    {"iso3": "LBN", "is_valid_manifest": True},
                    {"iso3": "BAD", "is_valid_manifest": False},
                ]
            )
            specs = build_worldpop_download_plan(tasks=tasks, worldpop_dir=Path(td))
            self.assertEqual(len(specs), 2)
            self.assertEqual([s.iso3 for s in specs], ["LBN", "YEM"])
            self.assertTrue(str(specs[0].output_path).endswith(build_worldpop_filename("LBN")))


if __name__ == "__main__":
    unittest.main()
