from __future__ import annotations

from pathlib import Path
from typing import Any

# River-cell -> population attribution for river-network hazard products
# (GloFAS discharge/SRI). GloFAS is meaningful on the river grid, not
# uniformly across every land pixel; a naive raster resample of the sparse
# GloFAS grid onto WorldPop would misattribute drought status to populations
# far from the affected reach. This module instead buffers each river reach
# into a corridor and assigns every population pixel within some corridor to
# its *nearest* reach, using a raster distance transform rather than a
# per-pixel KD-tree search so it composes with the existing rasterize/
# labelled_sum aggregation pattern used by every other hazard in this repo.

DEFAULT_STRAHLER_COLUMN = "ORD_STRA"


def _require(name: str):
    import importlib

    return importlib.import_module(name)


def load_river_reaches(
    hydrorivers_path: str | Path,
    layer: str | None = None,
    bbox: tuple[float, float, float, float] | None = None,
):
    """Load the HydroRIVERS reach layer, optionally pre-filtered to a bbox.

    HydroRIVERS v1.0 is a single global layer of ~8.5 million reaches;
    reading it with no `bbox` materializes every reach worldwide (minutes,
    multiple GB) before a caller can clip it down to one country. Always pass
    a country (buffered) bbox in `(west, south, east, north)` order -- the
    same convention used everywhere else in this repo -- to push the filter
    down to the reader instead.
    """

    gpd = _require("geopandas")
    path = Path(hydrorivers_path)
    if not path.exists():
        raise FileNotFoundError(f"HydroRIVERS dataset not found: {path.resolve()}")
    return gpd.read_file(path, layer=layer, bbox=bbox)


def clip_reaches_to_aoi(reaches_gdf, aoi_geom, out_crs: str = "EPSG:4326"):
    """Clip reaches to an AOI geometry (already in `out_crs`)."""

    gpd = _require("geopandas")

    reaches_4326 = reaches_gdf.to_crs(out_crs)
    clipped = gpd.clip(reaches_4326, aoi_geom)
    return clipped[~clipped.geometry.is_empty & clipped.geometry.notna()].reset_index(drop=True)


def corridor_widths_km(
    reaches_gdf,
    base_width_km: float = 5.0,
    per_order_km: float = 0.0,
    strahler_column: str = DEFAULT_STRAHLER_COLUMN,
):
    """Per-reach corridor half-width in km.

    Default is a flat `base_width_km` for every reach (the prototype default
    recommended in the implementation plan). Passing `per_order_km > 0` scales
    the corridor with Strahler order when that column is present, so larger
    rivers plausibly serve a wider population corridor than small headwater
    streams; falls back to the flat default when the column is absent.
    """

    np = _require("numpy")

    n = len(reaches_gdf)
    if strahler_column in reaches_gdf.columns and per_order_km > 0:
        order = reaches_gdf[strahler_column].to_numpy(dtype="float64")
        order = np.where(np.isfinite(order) & (order > 0), order, 1.0)
        return base_width_km + per_order_km * (order - 1.0)
    return np.full(n, float(base_width_km), dtype="float64")


def _representative_latitude(transform, out_shape: tuple[int, int]) -> float:
    height = out_shape[0]
    return float(transform.f + transform.e * (height / 2.0))


def _degree_sampling_km(transform, out_shape: tuple[int, int]) -> tuple[float, float]:
    """Approximate (row_km, col_km) pixel spacing for an EPSG:4326 grid.

    Uses a single representative latitude for the whole grid; adequate for
    country-scale AOIs but not for AOIs spanning many degrees of latitude.
    """

    import math

    lat0 = _representative_latitude(transform, out_shape)
    km_per_deg_lat = 110.574
    km_per_deg_lon = 111.320 * math.cos(math.radians(lat0))
    row_km = abs(transform.e) * km_per_deg_lat
    col_km = abs(transform.a) * max(km_per_deg_lon, 1e-6)
    return row_km, col_km


def rasterize_reach_labels(reaches_gdf, out_shape: tuple[int, int], transform, all_touched: bool = True):
    """Rasterize reach geometries; pixel value is 1-based reach index, 0 = no reach."""

    np = _require("numpy")
    rasterio_features = _require("rasterio.features")

    n = len(reaches_gdf)
    if n == 0:
        return np.zeros(out_shape, dtype="int32")
    shapes = [(geom, i + 1) for i, geom in enumerate(reaches_gdf.geometry) if geom is not None]
    if not shapes:
        return np.zeros(out_shape, dtype="int32")
    return rasterio_features.rasterize(
        shapes=shapes,
        out_shape=out_shape,
        transform=transform,
        fill=0,
        dtype="int32",
        all_touched=all_touched,
    )


def nearest_reach_transform(label_raster, transform, out_shape: tuple[int, int]):
    """For every pixel, the nearest reach's 0-based index and distance in km.

    Pixels with no reach anywhere in the grid get index -1 and distance inf.
    """

    np = _require("numpy")
    ndimage = _require("scipy.ndimage")

    if int(label_raster.max()) == 0:
        return (
            np.full(out_shape, -1, dtype="int32"),
            np.full(out_shape, np.inf, dtype="float64"),
        )

    sampling = _degree_sampling_km(transform, out_shape)
    background = label_raster == 0
    distances_km, indices = ndimage.distance_transform_edt(
        background, sampling=sampling, return_distances=True, return_indices=True
    )
    nearest_rows, nearest_cols = indices
    nearest_reach_index = label_raster[nearest_rows, nearest_cols].astype("int32") - 1
    return nearest_reach_index, distances_km


def build_river_corridor_mask(
    nearest_reach_index,
    distance_km,
    widths_km,
):
    """Boolean mask: pixel is within its nearest reach's corridor width."""

    np = _require("numpy")

    widths_arr = np.asarray(widths_km, dtype="float64")
    n = widths_arr.size
    has_reach = nearest_reach_index >= 0
    safe_index = np.clip(nearest_reach_index, 0, max(n - 1, 0))
    width_at_pixel = widths_arr[safe_index] if n > 0 else np.zeros_like(distance_km)
    return has_reach & (distance_km <= width_at_pixel)


def compute_river_corridor(
    reaches_gdf,
    out_shape: tuple[int, int],
    transform,
    *,
    base_width_km: float = 5.0,
    per_order_km: float = 0.0,
    strahler_column: str = DEFAULT_STRAHLER_COLUMN,
    all_touched: bool = True,
) -> dict[str, Any]:
    """End-to-end: reaches -> per-pixel nearest-reach corridor mask.

    Returns the corridor mask plus the nearest-reach index and distance
    rasters (so a caller can look up each pixel's reach-level SRI status) and
    the widths actually used per reach, for provenance in run_metadata.json.
    """

    widths_km = corridor_widths_km(
        reaches_gdf,
        base_width_km=base_width_km,
        per_order_km=per_order_km,
        strahler_column=strahler_column,
    )
    label_raster = rasterize_reach_labels(reaches_gdf, out_shape, transform, all_touched=all_touched)
    nearest_reach_index, distance_km = nearest_reach_transform(label_raster, transform, out_shape)
    mask = build_river_corridor_mask(nearest_reach_index, distance_km, widths_km)
    return {
        "mask": mask,
        "nearest_reach_index": nearest_reach_index,
        "distance_km": distance_km,
        "label_raster": label_raster,
        "widths_km": widths_km,
        "n_reaches": int(len(reaches_gdf)),
    }
