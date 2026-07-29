from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from wia_pipelines.hazards.flood_recurrence import (
    create_flood_recurrence_raster,
    discover_annual_flood_masks,
)


def _write_mask(path: Path, values: np.ndarray, *, transform=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=values.shape[1],
        height=values.shape[0],
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=transform or from_origin(20, 10, 0.1, 0.1),
        nodata=0,
    ) as destination:
        destination.write(values, 1)


def test_recurrence_counts_binary_annual_masks(tmp_path: Path) -> None:
    first = tmp_path / "first.tif"
    second = tmp_path / "second.tif"
    third = tmp_path / "third.tif"
    _write_mask(first, np.array([[0, 1], [1, 0]], dtype="uint8"))
    _write_mask(second, np.array([[0, 1], [0, 1]], dtype="uint8"))
    _write_mask(third, np.array([[0, 0], [1, 1]], dtype="uint8"))

    output = tmp_path / "recurrence.tif"
    counts = create_flood_recurrence_raster([first, second, third], output)

    with rasterio.open(output) as source:
        np.testing.assert_array_equal(source.read(1), np.array([[0, 2], [2, 2]], dtype="uint8"))
        assert source.nodata == 255
    assert counts == {0: 1, 1: 0, 2: 3, 3: 0}


def test_recurrence_rejects_mismatched_grids(tmp_path: Path) -> None:
    first = tmp_path / "first.tif"
    second = tmp_path / "second.tif"
    _write_mask(first, np.zeros((2, 2), dtype="uint8"))
    _write_mask(second, np.zeros((2, 2), dtype="uint8"), transform=from_origin(21, 10, 0.1, 0.1))
    with pytest.raises(ValueError, match="identical"):
        create_flood_recurrence_raster([first, second], tmp_path / "result.tif")


def test_discover_annual_masks_requires_every_year(tmp_path: Path) -> None:
    mask = tmp_path / "SSD/2021-12-31_m12/flood" / "rasters/flood/SSD_flood_any_2021-01-01_2021-12-31.tif"
    _write_mask(mask, np.zeros((2, 2), dtype="uint8"))
    assert discover_annual_flood_masks(tmp_path, "ssd", 2021, 2021) == [(2021, mask)]
    with pytest.raises(FileNotFoundError, match="2022"):
        discover_annual_flood_masks(tmp_path, "SSD", 2021, 2022)
