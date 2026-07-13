from __future__ import annotations

from pathlib import Path
from typing import Any


def _require(name: str):
    import importlib

    return importlib.import_module(name)


def worldpop_profile_and_bounds(
    worldpop_path: str | Path,
    band: int = 1,
) -> dict[str, Any]:
    rasterio = _require("rasterio")
    gpd = _require("geopandas")
    shapely_geometry = _require("shapely.geometry")

    path = Path(worldpop_path)
    if not path.exists():
        raise FileNotFoundError(f"WorldPop raster not found: {path.resolve()}")

    with rasterio.open(path) as src:
        if band < 1 or band > src.count:
            raise ValueError(f"Band {band} is out of range for raster with {src.count} bands.")
        bounds_geom = shapely_geometry.box(*src.bounds)
        if src.crs is not None:
            bounds_4326 = gpd.GeoSeries([bounds_geom], crs=src.crs).to_crs("EPSG:4326").iloc[0].bounds
        else:
            bounds_4326 = src.bounds

        return {
            "bounds_4326": tuple(float(v) for v in bounds_4326),
            "profile": {
                "driver": src.driver,
                "dtype": src.dtypes[band - 1],
                "nodata": src.nodatavals[band - 1],
                "width": src.width,
                "height": src.height,
                "count": src.count,
                "crs": str(src.crs) if src.crs else None,
                "transform": tuple(src.transform),
                "bounds_native": tuple(float(v) for v in src.bounds),
            },
        }


def worldpop_valid_mask(worldpop_path: str | Path, band: int = 1):
    rasterio = _require("rasterio")
    np = _require("numpy")

    with rasterio.open(Path(worldpop_path)) as src:
        arr = src.read(band)
        nodata = src.nodatavals[band - 1]
        if nodata is None:
            mask = np.isfinite(arr)
        else:
            mask = np.isfinite(arr) & (arr != nodata)
        return mask, src.profile


def bbox_coverage_report(
    target_bounds: tuple[float, float, float, float],
    raster_bounds: tuple[float, float, float, float],
) -> dict[str, Any]:
    shapely_geometry = _require("shapely.geometry")

    target_box = shapely_geometry.box(*target_bounds)
    raster_box = shapely_geometry.box(*raster_bounds)
    inter = target_box.intersection(raster_box)
    covered_pct = 0.0 if target_box.area == 0 else (inter.area / target_box.area) * 100.0
    full = raster_box.contains(target_box) or raster_box.equals(target_box)

    warnings = []
    if not full:
        warnings.append("Raster bounds do not fully cover target bounds.")
    if covered_pct < 100.0:
        warnings.append(f"Coverage is {covered_pct:.2f}% (<100%).")

    return {
        "coverage_pct": float(covered_pct),
        "full_coverage": bool(full),
        "warnings": warnings,
    }
