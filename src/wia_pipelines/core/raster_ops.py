from __future__ import annotations

from pathlib import Path
from typing import Any


def _require(name: str):
    import importlib

    return importlib.import_module(name)


def write_array_geotiff(
    path: str | Path,
    array,
    transform: Any,
    crs: Any,
    nodata: float | int | None = None,
    dtype: str | None = None,
) -> Path:
    rasterio = _require("rasterio")

    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    arr = array
    out_dtype = dtype or str(arr.dtype)
    profile = {
        "driver": "GTiff",
        "height": int(arr.shape[0]),
        "width": int(arr.shape[1]),
        "count": 1,
        "dtype": out_dtype,
        "crs": crs,
        "transform": transform,
        "nodata": nodata,
        "compress": "deflate",
    }
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(arr.astype(out_dtype), 1)
    return out_path


def reproject_array_to_grid(
    src_array,
    src_transform,
    src_crs,
    dst_shape: tuple[int, int],
    dst_transform,
    dst_crs,
    src_nodata: float | int | None = None,
    dst_nodata: float | int | None = None,
    resampling: str = "nearest",
):
    np = _require("numpy")
    rasterio_warp = _require("rasterio.warp")
    rasterio_enums = _require("rasterio.enums")

    resampling_enum = {
        "nearest": rasterio_enums.Resampling.nearest,
        "bilinear": rasterio_enums.Resampling.bilinear,
        "average": rasterio_enums.Resampling.average,
    }.get(resampling.lower())
    if resampling_enum is None:
        raise ValueError(f"Unsupported resampling '{resampling}'.")

    dst = np.full(dst_shape, dst_nodata if dst_nodata is not None else 0, dtype=src_array.dtype)
    rasterio_warp.reproject(
        source=src_array,
        destination=dst,
        src_transform=src_transform,
        src_crs=src_crs,
        src_nodata=src_nodata,
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        dst_nodata=dst_nodata,
        resampling=resampling_enum,
    )
    return dst


def align_to_reference(
    src_path: str | Path,
    ref_path: str | Path,
    src_band: int = 1,
    ref_band: int = 1,
    resampling: str = "nearest",
):
    rasterio = _require("rasterio")

    with rasterio.open(Path(src_path)) as src, rasterio.open(Path(ref_path)) as ref:
        src_array = src.read(src_band)
        aligned = reproject_array_to_grid(
            src_array=src_array,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_shape=(ref.height, ref.width),
            dst_transform=ref.transform,
            dst_crs=ref.crs,
            src_nodata=src.nodatavals[src_band - 1],
            dst_nodata=src.nodatavals[src_band - 1],
            resampling=resampling,
        )
        profile = ref.profile.copy()
        profile.update(
            {
                "dtype": str(aligned.dtype),
                "nodata": src.nodatavals[src_band - 1],
                "count": 1,
            }
        )
        _ = ref_band  # currently reference band is only used for shape/grid selection.
    return aligned, profile
