from __future__ import annotations

from typing import Iterable


def _require(name: str):
    import importlib

    return importlib.import_module(name)


def zonal_sum(
    array,
    transform,
    geometries: Iterable,
    nodata: float | int | None = None,
) -> list[float]:
    np = _require("numpy")
    rasterio_features = _require("rasterio.features")
    shapely_geometry = _require("shapely.geometry")

    arr = np.asarray(array)
    if arr.ndim != 2:
        raise ValueError(f"Expected 2D array, got shape {arr.shape}.")

    valid = np.isfinite(arr)
    if nodata is not None:
        valid &= arr != nodata

    results: list[float] = []
    for geom in geometries:
        mask = rasterio_features.geometry_mask(
            [shapely_geometry.mapping(geom)],
            out_shape=arr.shape,
            transform=transform,
            invert=True,
        )
        total = float(np.nansum(arr[mask & valid]))
        results.append(total)
    return results
