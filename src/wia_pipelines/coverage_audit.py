from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import rasterio
import xarray as xr
from pyproj import Geod
from shapely.geometry import box
from shapely.ops import unary_union


_GEOD = Geod(ellps="WGS84")


@dataclass(frozen=True)
class LayerSpec:
    name: str
    path: Path


def _validate_iso3(iso3: str) -> str:
    value = (iso3 or "").strip().upper()
    if len(value) != 3 or not value.isalpha():
        raise ValueError(f"iso3 must be a 3-letter country code, got '{iso3}'.")
    return value


def _load_country_bounds_4326(
    iso3: str,
    admin_path: Path,
    admin_layer: str,
    iso3_field: str = "iso3",
    adm_level_field: str | None = None,
    target_adm_level: int | None = None,
    buffer_km: float = 0.0,
) -> tuple[tuple[float, float, float, float], Any]:
    if not admin_path.exists():
        raise FileNotFoundError(f"Admin boundaries source not found: {admin_path.resolve()}")

    gdf = gpd.read_file(admin_path, layer=admin_layer)
    if iso3_field not in gdf.columns:
        raise KeyError(f"'{iso3_field}' not found in admin boundaries columns: {list(gdf.columns)}")

    iso3_norm = _validate_iso3(iso3)
    country = gdf[gdf[iso3_field].astype(str).str.upper() == iso3_norm].copy()
    if country.empty:
        raise ValueError(f"No admin features found for iso3='{iso3_norm}' in layer '{admin_layer}'.")

    if adm_level_field and target_adm_level is not None:
        if adm_level_field not in country.columns:
            raise KeyError(
                f"'{adm_level_field}' not found in admin boundaries columns: {list(country.columns)}"
            )
        country = country[country[adm_level_field] == target_adm_level].copy()
        if country.empty:
            raise ValueError(f"No features for iso3='{iso3_norm}' with {adm_level_field}={target_adm_level}.")

    country = country[country.geometry.notna()].copy()
    if country.empty:
        raise ValueError("Country admin boundaries have no valid geometry.")

    country_4326 = country.to_crs("EPSG:4326")
    geom = unary_union(country_4326.geometry)
    if buffer_km > 0:
        # Approximate buffer in degrees for a fast audit pass.
        buffer_deg = buffer_km / 111.32
        geom = geom.buffer(buffer_deg)

    bounds = tuple(float(v) for v in geom.bounds)
    return bounds, geom


def _bbox_area_km2(bounds: tuple[float, float, float, float]) -> float:
    minx, miny, maxx, maxy = bounds
    ring_lon = [minx, maxx, maxx, minx, minx]
    ring_lat = [miny, miny, maxy, maxy, miny]
    area_m2, _ = _GEOD.polygon_area_perimeter(ring_lon, ring_lat)
    return abs(area_m2) / 1_000_000.0


def _bounds_from_raster(path: Path) -> tuple[float, float, float, float]:
    with rasterio.open(path) as src:
        src_bounds_geom = box(*src.bounds)
        if src.crs:
            bounds_4326 = gpd.GeoSeries([src_bounds_geom], crs=src.crs).to_crs("EPSG:4326").iloc[0].bounds
        else:
            bounds_4326 = src.bounds
    return tuple(float(v) for v in bounds_4326)


def _bounds_from_netcdf(path: Path) -> tuple[float, float, float, float]:
    ds = xr.open_dataset(path)
    try:
        lon_name = next((k for k in ("lon", "longitude", "x") if k in ds.coords), None)
        lat_name = next((k for k in ("lat", "latitude", "y") if k in ds.coords), None)
        if lon_name is None or lat_name is None:
            raise ValueError(f"Could not infer longitude/latitude coordinates in NetCDF: {path.name}")

        lon = ds.coords[lon_name].values
        lat = ds.coords[lat_name].values
        lon_min, lon_max = float(lon.min()), float(lon.max())
        lat_min, lat_max = float(lat.min()), float(lat.max())
        return (lon_min, lat_min, lon_max, lat_max)
    finally:
        ds.close()


def _bounds_for_layer(path: Path) -> tuple[float, float, float, float]:
    suffix = path.suffix.lower()
    if suffix in {".nc", ".nc4", ".cdf"}:
        return _bounds_from_netcdf(path)
    return _bounds_from_raster(path)


def _coverage_pct(
    admin_bounds: tuple[float, float, float, float],
    layer_bounds: tuple[float, float, float, float],
) -> float:
    admin_box = box(*admin_bounds)
    layer_box = box(*layer_bounds)
    inter = admin_box.intersection(layer_box)
    if admin_box.area == 0:
        return 0.0
    return float((inter.area / admin_box.area) * 100.0)


def audit_hazard_layer_coverage(
    iso3: str,
    admin_path: str | Path,
    admin_layer: str,
    layers: list[LayerSpec],
    iso3_field: str = "iso3",
    adm_level_field: str | None = None,
    target_adm_level: int | None = None,
    buffer_km: float = 0.0,
) -> dict[str, Any]:
    admin_bounds, _ = _load_country_bounds_4326(
        iso3=iso3,
        admin_path=Path(admin_path),
        admin_layer=admin_layer,
        iso3_field=iso3_field,
        adm_level_field=adm_level_field,
        target_adm_level=target_adm_level,
        buffer_km=buffer_km,
    )

    admin_area_km2 = _bbox_area_km2(admin_bounds)

    rows: list[dict[str, Any]] = []
    for spec in layers:
        if not spec.path.exists():
            rows.append(
                {
                    "layer": spec.name,
                    "path": str(spec.path),
                    "exists": False,
                    "layer_bounds_4326": None,
                    "coverage_pct_of_admin_bbox": 0.0,
                    "fully_covers_admin_bbox": False,
                    "status": "missing_file",
                }
            )
            continue

        try:
            layer_bounds = _bounds_for_layer(spec.path)
            coverage_pct = _coverage_pct(admin_bounds, layer_bounds)
            fully_covers = coverage_pct >= 99.999
            status = "ok"
        except Exception as exc:
            rows.append(
                {
                    "layer": spec.name,
                    "path": str(spec.path),
                    "exists": True,
                    "layer_bounds_4326": None,
                    "coverage_pct_of_admin_bbox": 0.0,
                    "fully_covers_admin_bbox": False,
                    "status": f"error: {exc}",
                }
            )
            continue

        rows.append(
            {
                "layer": spec.name,
                "path": str(spec.path),
                "exists": True,
                "layer_bounds_4326": layer_bounds,
                "coverage_pct_of_admin_bbox": round(coverage_pct, 3),
                "fully_covers_admin_bbox": fully_covers,
                "status": status,
            }
        )

    results_df = pd.DataFrame(rows)
    return {
        "iso3": _validate_iso3(iso3),
        "admin_bounds_4326": admin_bounds,
        "admin_bbox_area_km2": round(admin_area_km2, 3),
        "layer_results": results_df,
    }
