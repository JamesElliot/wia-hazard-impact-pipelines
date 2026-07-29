from __future__ import annotations

from pathlib import Path
from typing import Any


def _cell_edges_from_centers(vals) -> Any:
    import numpy as np

    vals = np.asarray(vals, dtype="float64")
    if vals.ndim != 1 or vals.size < 2:
        raise ValueError("Coordinate array must be 1D with at least 2 values.")
    diffs = np.diff(vals)
    start = vals[0] - diffs[0] / 2.0
    end = vals[-1] + diffs[-1] / 2.0
    mids = (vals[:-1] + vals[1:]) / 2.0
    return np.concatenate([[start], mids, [end]])


def _pick_plottable_da(ds):
    # Prefer variables with explicit 2D/3D spatial dims.
    for var in ds.data_vars:
        if var.lower() == "crs":
            continue
        da = ds[var]
        dims = set(da.dims)
        if {"lat", "lon"}.issubset(dims) or {"latitude", "longitude"}.issubset(dims):
            return da

    # Fallback: any variable that has x/y style dims.
    for var in ds.data_vars:
        if var.lower() == "crs":
            continue
        da = ds[var]
        dims = set(da.dims)
        if {"x", "y"}.issubset(dims):
            return da
    return None


def _sample_indices(size: int, max_lines: int = 80) -> Any:
    import numpy as np

    if size <= max_lines:
        return np.arange(size)
    return np.unique(np.linspace(0, size - 1, max_lines).astype(int))


def _plot_admin_and_aoi(ax, admin_gdf, admin_bounds_wsen: tuple[float, float, float, float]) -> None:
    import geopandas as gpd
    from shapely.geometry import box

    admin_4326 = admin_gdf.to_crs("EPSG:4326")
    admin_4326.boundary.plot(ax=ax, linewidth=0.7, color="black")
    aoi_bbox = gpd.GeoSeries([box(*admin_bounds_wsen)], crs="EPSG:4326")
    aoi_bbox.boundary.plot(ax=ax, linewidth=1.2, color="red", linestyle="--")


def plot_raster_overlay_figure(
    admin_gdf,
    admin_bounds_wsen: tuple[float, float, float, float],
    source_path: Path,
    source_type: str,
    out_png: Path,
    title: str,
    max_dim: int = 1200,
) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    out_png.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(9, 9))

    if source_type == "raster":
        import geopandas as gpd
        import rasterio
        from rasterio.enums import Resampling
        from shapely.geometry import box

        with rasterio.open(source_path) as src:
            scale = max(src.width / max_dim, src.height / max_dim, 1.0)
            out_w = max(1, int(src.width / scale))
            out_h = max(1, int(src.height / scale))
            arr = src.read(
                1,
                out_shape=(out_h, out_w),
                resampling=Resampling.nearest,
                masked=True,
            ).astype("float64")
            if src.nodata is not None:
                arr[arr == float(src.nodata)] = np.nan

            bounds_geom = box(*src.bounds)
            if src.crs:
                bounds_4326 = gpd.GeoSeries([bounds_geom], crs=src.crs).to_crs("EPSG:4326").iloc[0].bounds
            else:
                bounds_4326 = src.bounds

        extent = [bounds_4326[0], bounds_4326[2], bounds_4326[1], bounds_4326[3]]
        im = ax.imshow(arr, extent=extent, origin="upper", cmap="viridis")
        fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    elif source_type == "netcdf":
        import xarray as xr

        ds = xr.open_dataset(source_path)
        try:
            da = _pick_plottable_da(ds)
            if da is None:
                raise ValueError(f"No plottable data variable found in {source_path.name}.")
            if "time" in da.dims:
                da = da.isel(time=0)

            rename = {}
            if "latitude" in da.dims:
                rename["latitude"] = "lat"
            if "longitude" in da.dims:
                rename["longitude"] = "lon"
            if rename:
                da = da.rename(rename)

            if "lat" not in da.dims or "lon" not in da.dims:
                raise ValueError(f"Expected lat/lon dims in {source_path.name}, got {da.dims}.")

            arr = da.values.astype("float64")
            lats = da["lat"].values
            lons = da["lon"].values
            lat_edges = _cell_edges_from_centers(lats)
            lon_edges = _cell_edges_from_centers(lons)
            extent = [
                float(lon_edges.min()),
                float(lon_edges.max()),
                float(lat_edges.min()),
                float(lat_edges.max()),
            ]
            im = ax.imshow(arr, extent=extent, origin="upper", cmap="viridis")
            fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
        finally:
            ds.close()
    else:
        raise ValueError(f"Unsupported source_type '{source_type}'. Expected 'raster' or 'netcdf'.")

    _plot_admin_and_aoi(ax, admin_gdf, admin_bounds_wsen)
    ax.set_title(title)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_aspect("equal")
    plt.tight_layout()
    fig.savefig(out_png, dpi=200)
    plt.close(fig)
    return out_png


def plot_flood_item_extents_figure(
    admin_gdf,
    admin_bounds_wsen: tuple[float, float, float, float],
    item_bboxes_4326: list[list[float]],
    out_png: Path,
    title: str,
) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import geopandas as gpd
    import matplotlib.pyplot as plt
    from shapely.geometry import box

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 9))

    _plot_admin_and_aoi(ax, admin_gdf, admin_bounds_wsen)

    if item_bboxes_4326:
        geoms = [box(*b) for b in item_bboxes_4326]
        gdf = gpd.GeoDataFrame({"idx": list(range(len(geoms)))}, geometry=geoms, crs="EPSG:4326")
        gdf.boundary.plot(ax=ax, color="#1f77b4", linewidth=0.8, alpha=0.7)

    ax.set_title(title)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_aspect("equal")
    plt.tight_layout()
    fig.savefig(out_png, dpi=200)
    plt.close(fig)
    return out_png


def plot_grid_overlay_figure(
    admin_gdf,
    admin_bounds_wsen: tuple[float, float, float, float],
    source_path: Path,
    source_type: str,
    out_png: Path,
    title: str,
    max_lines: int = 80,
) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    out_png.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(9, 9))

    if source_type == "raster":
        import geopandas as gpd
        import pyproj
        import rasterio
        from shapely.geometry import box

        with rasterio.open(source_path) as src:
            width = src.width
            height = src.height
            t = src.transform
            xs = t.c + np.arange(width + 1) * t.a
            ys = t.f + np.arange(height + 1) * t.e
            ix = _sample_indices(len(xs), max_lines=max_lines)
            iy = _sample_indices(len(ys), max_lines=max_lines)

            bounds_geom = box(*src.bounds)
            if src.crs:
                bounds_4326 = gpd.GeoSeries([bounds_geom], crs=src.crs).to_crs("EPSG:4326").iloc[0].bounds
            else:
                bounds_4326 = src.bounds

        extent = [bounds_4326[0], bounds_4326[2], bounds_4326[1], bounds_4326[3]]
        if src.crs and str(src.crs) != "EPSG:4326":
            transformer = pyproj.Transformer.from_crs(src.crs, "EPSG:4326", always_xy=True)
            y_curve = np.linspace(float(ys.min()), float(ys.max()), 200)
            x_curve = np.linspace(float(xs.min()), float(xs.max()), 200)
            for i in ix:
                x = float(xs[i])
                xx = np.full_like(y_curve, x, dtype="float64")
                lon, lat = transformer.transform(xx, y_curve)
                ax.plot(lon, lat, color="#1f77b4", alpha=0.35, linewidth=0.6)
            for j in iy:
                y = float(ys[j])
                yy = np.full_like(x_curve, y, dtype="float64")
                lon, lat = transformer.transform(x_curve, yy)
                ax.plot(lon, lat, color="#1f77b4", alpha=0.35, linewidth=0.6)
        else:
            for i in ix:
                x = float(xs[i])
                ax.plot([x, x], [extent[2], extent[3]], color="#1f77b4", alpha=0.35, linewidth=0.6)
            for j in iy:
                y = float(ys[j])
                ax.plot([extent[0], extent[1]], [y, y], color="#1f77b4", alpha=0.35, linewidth=0.6)
    elif source_type == "netcdf":
        import xarray as xr

        ds = xr.open_dataset(source_path)
        try:
            da = _pick_plottable_da(ds)
            if da is None:
                raise ValueError(f"No plottable data variable found in {source_path.name}.")
            rename = {}
            if "latitude" in da.dims:
                rename["latitude"] = "lat"
            if "longitude" in da.dims:
                rename["longitude"] = "lon"
            if rename:
                da = da.rename(rename)
            lats = da["lat"].values
            lons = da["lon"].values
            lat_edges = _cell_edges_from_centers(lats)
            lon_edges = _cell_edges_from_centers(lons)

            ix = _sample_indices(len(lon_edges), max_lines=max_lines)
            iy = _sample_indices(len(lat_edges), max_lines=max_lines)
            for i in ix:
                x = float(lon_edges[i])
                ax.plot(
                    [x, x],
                    [float(lat_edges.min()), float(lat_edges.max())],
                    color="#1f77b4",
                    alpha=0.35,
                    linewidth=0.6,
                )
            for j in iy:
                y = float(lat_edges[j])
                ax.plot(
                    [float(lon_edges.min()), float(lon_edges.max())],
                    [y, y],
                    color="#1f77b4",
                    alpha=0.35,
                    linewidth=0.6,
                )
        finally:
            ds.close()
    else:
        raise ValueError(f"Unsupported source_type '{source_type}'. Expected 'raster' or 'netcdf'.")

    _plot_admin_and_aoi(ax, admin_gdf, admin_bounds_wsen)
    ax.set_title(title)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_aspect("equal")
    plt.tight_layout()
    fig.savefig(out_png, dpi=200)
    plt.close(fig)
    return out_png
