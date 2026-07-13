from __future__ import annotations

import calendar
from pathlib import Path
from typing import Any

from ..core.admin import build_admin_aoi, filter_admin_for_iso3, load_admin_layer
from ..core.cds import download_cds, extract_zip_to_dir
from ..core.worldpop import bbox_coverage_report, worldpop_profile_and_bounds


def days_for_year_month(year: int, month: int) -> list[str]:
    last_day = calendar.monthrange(year, month)[1]
    return [f"{d:02d}" for d in range(1, last_day + 1)]


def spei_sample_request(
    year: int,
    month: int,
    area_nwse: list[float],
) -> dict[str, Any]:
    return {
        "variable": ["standardised_precipitation_evapotranspiration_index"],
        "accumulation_period": ["3"],
        "version": "1_0",
        "product_type": ["reanalysis"],
        "dataset_type": "consolidated_dataset",
        "year": [str(year)],
        "month": [f"{month:02d}"],
        "area": area_nwse,
    }


def utci_sample_request(
    year: int,
    month: int,
    area_nwse: list[float],
) -> dict[str, Any]:
    return {
        "variable": ["universal_thermal_climate_index_daily_statistics"],
        "version": "1_1",
        "product_type": "consolidated_dataset",
        "year": [str(year)],
        "month": [f"{month:02d}"],
        "day": days_for_year_month(year, month),
        "area": area_nwse,
    }


def netcdf_bounds_4326(path: Path) -> tuple[float, float, float, float]:
    import xarray as xr

    ds = xr.open_dataset(path)
    try:
        lon_name = next((k for k in ("lon", "longitude", "x") if k in ds.coords), None)
        lat_name = next((k for k in ("lat", "latitude", "y") if k in ds.coords), None)
        if lon_name is None or lat_name is None:
            raise ValueError(f"Could not infer lon/lat coordinate names in {path.name}")
        lon = ds.coords[lon_name].values
        lat = ds.coords[lat_name].values
        return (float(lon.min()), float(lat.min()), float(lon.max()), float(lat.max()))
    finally:
        ds.close()


def raster_bounds_4326(path: Path) -> tuple[float, float, float, float]:
    import geopandas as gpd
    import rasterio
    from shapely.geometry import box

    with rasterio.open(path) as src:
        bounds_geom = box(*src.bounds)
        if src.crs is None:
            return tuple(float(v) for v in src.bounds)
        bounds = gpd.GeoSeries([bounds_geom], crs=src.crs).to_crs("EPSG:4326").iloc[0].bounds
    return tuple(float(v) for v in bounds)


def prepare_country_admin_context(
    iso3: str,
    admin_path: Path,
    admin_layer: str = "admin2",
    iso3_field: str = "iso3",
    buffer_km: float = 0.0,
    cds_buffer_deg: float = 0.25,
) -> dict[str, Any]:
    admin_all = load_admin_layer(admin_path, layer=admin_layer)
    admin_country = filter_admin_for_iso3(admin_all, iso3=iso3, iso3_field=iso3_field)
    aoi = build_admin_aoi(admin_country, buffer_km=buffer_km, out_crs="EPSG:4326")
    west, south, east, north = aoi["admin_bounds"]
    west_b = max(-180.0, west - cds_buffer_deg)
    south_b = max(-90.0, south - cds_buffer_deg)
    east_b = min(180.0, east + cds_buffer_deg)
    north_b = min(90.0, north + cds_buffer_deg)
    return {
        "iso3": iso3.upper(),
        "admin_gdf": admin_country,
        "admin_bounds_wsen": (west, south, east, north),
        "cds_bounds_wsen": (west_b, south_b, east_b, north_b),
        "cds_area_nwse": [north_b, west_b, south_b, east_b],
        "cds_buffer_deg": cds_buffer_deg,
    }


def check_worldpop_coverage(
    admin_bounds_wsen: tuple[float, float, float, float], worldpop_path: Path
) -> dict[str, Any]:
    wp = worldpop_profile_and_bounds(worldpop_path)
    report = bbox_coverage_report(admin_bounds_wsen, wp["bounds_4326"])
    return {
        "worldpop_path": str(worldpop_path),
        "worldpop_bounds_4326": wp["bounds_4326"],
        "coverage_pct": report["coverage_pct"],
        "full_coverage": report["full_coverage"],
        "warnings": report["warnings"],
    }


def run_cds_single_month_check(
    dataset: str,
    request: dict[str, Any],
    output_zip: Path,
) -> dict[str, Any]:
    if output_zip.exists() and output_zip.stat().st_size > 0:
        ok, err = True, None
    else:
        ok, err = download_cds(dataset, request, output_zip)
    result: dict[str, Any] = {
        "ok": ok,
        "error": err,
        "zip_path": str(output_zip),
        "zip_exists": output_zip.exists(),
        "zip_size": output_zip.stat().st_size if output_zip.exists() else 0,
        "n_nc_files": 0,
        "first_nc_path": None,
        "sample_bounds_4326": None,
    }
    if not ok:
        return result

    extracted = extract_zip_to_dir(output_zip, output_zip.parent / "extracted")
    result["n_nc_files"] = len(extracted)
    if extracted:
        result["first_nc_path"] = str(extracted[0])
        result["sample_bounds_4326"] = netcdf_bounds_4326(extracted[0])
    return result


def run_flood_single_asset_check(
    iso3: str,
    admin_gdf,
    output_tif: Path,
    admin_bounds_wsen: tuple[float, float, float, float],
    stac_api_url: str = "https://stac.eodc.eu/api/v1",
    collection_id: str = "GFM",
    asset_key: str = "ensemble_flood_extent",
    datetime_range: str = "2025-01-01/2025-01-31",
    selection_mode: str = "best",
) -> dict[str, Any]:
    import requests
    from pystac_client import Client
    from shapely.geometry import box, mapping
    from shapely.ops import unary_union

    country_geom_4326 = admin_gdf.to_crs("EPSG:4326").geometry.union_all()
    admin_box = box(*admin_bounds_wsen)

    out = {
        "ok": False,
        "error": None,
        "asset_path": str(output_tif),
        "asset_href": None,
        "sample_bounds_4326": None,
        "item_id": None,
        "item_count": 0,
        "selection_mode": selection_mode,
        "collection_id": collection_id,
        "asset_key": asset_key,
        "item_bbox_coverage_pct": None,
        "mosaic_bbox_coverage_pct": None,
        "cached_file_used": False,
    }

    if output_tif.exists() and output_tif.stat().st_size > 0:
        out["sample_bounds_4326"] = raster_bounds_4326(output_tif)
        out["ok"] = True
        out["cached_file_used"] = True
        return out

    def _select_candidate_by_mode(cands, mode: str):
        if mode == "first":
            return cands[0][0], max(cands, key=lambda x: x[1])[1]
        chosen_item, best_cov = max(cands, key=lambda x: x[1])
        return chosen_item, best_cov

    try:
        client = Client.open(stac_api_url)
        search = client.search(
            collections=[collection_id],
            intersects=mapping(country_geom_4326),
            datetime=datetime_range,
        )
        items = list(search.items())
        if not items:
            out["error"] = f"No STAC items found for {iso3} in {datetime_range}."
            return out
        out["item_count"] = len(items)

        candidates = []
        for item in items:
            if asset_key in item.assets:
                if item.bbox is None:
                    continue
                ibox = box(*item.bbox)
                inter = admin_box.intersection(ibox)
                cov_pct = 0.0 if admin_box.area == 0 else float((inter.area / admin_box.area) * 100.0)
                candidates.append((item, cov_pct))
        if not candidates:
            out["error"] = f"No STAC items with asset '{asset_key}' found."
            return out

        if selection_mode not in {"first", "best", "mosaic"}:
            out["error"] = f"Unsupported selection_mode '{selection_mode}'."
            return out

        chosen, best_cov = _select_candidate_by_mode(candidates, selection_mode)
        out["item_bbox_coverage_pct"] = best_cov

        if selection_mode == "mosaic":
            union = unary_union([box(*c[0].bbox) for c in candidates if c[0].bbox])
            inter = admin_box.intersection(union)
            mosaic_cov = 0.0 if admin_box.area == 0 else float((inter.area / admin_box.area) * 100.0)
            out["mosaic_bbox_coverage_pct"] = mosaic_cov

        asset = chosen.assets[asset_key]
        href = asset.href
        out["asset_href"] = href
        out["item_id"] = chosen.id
        output_tif.parent.mkdir(parents=True, exist_ok=True)

        with requests.get(href, stream=True, timeout=180) as resp:
            resp.raise_for_status()
            with output_tif.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 512):
                    if chunk:
                        f.write(chunk)

        out["sample_bounds_4326"] = raster_bounds_4326(output_tif)
        out["ok"] = True
        return out
    except Exception as exc:
        out["error"] = str(exc)
        return out


def run_flood_stac_extent_check(
    iso3: str,
    admin_gdf,
    admin_bounds_wsen: tuple[float, float, float, float],
    stac_api_url: str = "https://stac.eodc.eu/api/v1",
    collection_id: str = "GFM",
    asset_key: str = "ensemble_flood_extent",
    datetime_range: str = "2025-01-01/2025-01-31",
) -> dict[str, Any]:
    from pystac_client import Client
    from shapely.geometry import box, mapping
    from shapely.ops import unary_union

    country_geom_4326 = admin_gdf.to_crs("EPSG:4326").geometry.union_all()
    admin_box = box(*admin_bounds_wsen)

    out = {
        "ok": False,
        "error": None,
        "collection_id": collection_id,
        "asset_key": asset_key,
        "item_count": 0,
        "item_ids": [],
        "item_bboxes_4326": [],
        "item_bbox_coverages_pct": [],
        "union_bbox_coverage_pct": 0.0,
        "union_full_coverage": False,
        "datetime_range": datetime_range,
    }
    try:
        client = Client.open(stac_api_url)
        search = client.search(
            collections=[collection_id],
            intersects=mapping(country_geom_4326),
            datetime=datetime_range,
        )
        items = list(search.items())
        if not items:
            out["error"] = f"No STAC items found for {iso3} in {datetime_range}."
            return out

        candidates = []
        for item in items:
            if asset_key not in item.assets:
                continue
            if item.bbox is None:
                continue
            ibox = box(*item.bbox)
            inter = admin_box.intersection(ibox)
            cov_pct = 0.0 if admin_box.area == 0 else float((inter.area / admin_box.area) * 100.0)
            candidates.append((item, cov_pct))

        if not candidates:
            out["error"] = f"No STAC items with asset '{asset_key}' and bbox metadata found."
            return out

        out["item_count"] = len(candidates)
        out["item_ids"] = [c[0].id for c in candidates]
        out["item_bboxes_4326"] = [list(c[0].bbox) for c in candidates]
        out["item_bbox_coverages_pct"] = [float(c[1]) for c in candidates]

        union = unary_union([box(*c[0].bbox) for c in candidates])
        inter = admin_box.intersection(union)
        union_cov = 0.0 if admin_box.area == 0 else float((inter.area / admin_box.area) * 100.0)
        out["union_bbox_coverage_pct"] = union_cov
        out["union_full_coverage"] = union_cov >= 99.999
        out["ok"] = True
        return out
    except Exception as exc:
        out["error"] = str(exc)
        return out


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
