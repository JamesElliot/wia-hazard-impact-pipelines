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


def labelled_sum(
    labels,
    values,
    *,
    n_labels: int,
    valid_mask=None,
) -> list[float]:
    """Sum a raster by positive integer labels, returning labels 1..n_labels."""

    np = _require("numpy")
    label_array = np.asarray(labels)
    value_array = np.asarray(values)
    if label_array.shape != value_array.shape:
        raise ValueError(
            f"labels and values must have the same shape, got {label_array.shape} and {value_array.shape}."
        )
    if int(n_labels) < 0:
        raise ValueError(f"n_labels must be >= 0, got {n_labels}.")

    valid = (label_array > 0) & (label_array <= int(n_labels)) & np.isfinite(value_array)
    if valid_mask is not None:
        mask = np.asarray(valid_mask, dtype=bool)
        if mask.shape != label_array.shape:
            raise ValueError(f"valid_mask must match labels shape, got {mask.shape} and {label_array.shape}.")
        valid &= mask

    sums = np.bincount(
        label_array[valid].astype("int64", copy=False),
        weights=value_array[valid].astype("float64", copy=False),
        minlength=int(n_labels) + 1,
    )
    return sums[1 : int(n_labels) + 1].astype("float64").tolist()
