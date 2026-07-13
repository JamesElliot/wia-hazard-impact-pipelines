from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


def _require(name: str):
    import importlib

    module = importlib.import_module(name)
    return module


def _validate_iso3(iso3: str) -> str:
    value = (iso3 or "").strip().upper()
    if len(value) != 3 or not value.isalpha():
        raise ValueError(f"iso3 must be a 3-letter country code, got '{iso3}'.")
    return value


def load_admin_layer(admin_path: str | Path, layer: str | None = None):
    gpd = _require("geopandas")
    admin_path = Path(admin_path)
    if not admin_path.exists():
        raise FileNotFoundError(f"Admin dataset not found: {admin_path.resolve()}")
    return gpd.read_file(admin_path, layer=layer)


def filter_admin_for_iso3(
    gdf,
    iso3: str,
    iso3_field: str = "iso3",
    adm_level_field: str | None = None,
    target_adm_level: int | None = None,
):
    iso3_norm = _validate_iso3(iso3)
    if iso3_field not in gdf.columns:
        raise KeyError(f"'{iso3_field}' not found in admin columns.")
    filtered = gdf[gdf[iso3_field].astype(str).str.upper() == iso3_norm].copy()
    if filtered.empty:
        raise ValueError(f"No admin features found for iso3='{iso3_norm}'.")
    if adm_level_field and target_adm_level is not None:
        if adm_level_field not in filtered.columns:
            raise KeyError(f"'{adm_level_field}' not found in admin columns.")
        filtered = filtered[filtered[adm_level_field] == target_adm_level].copy()
    filtered = filtered[filtered.geometry.notna()].copy()
    if filtered.empty:
        raise ValueError("No non-null geometries after filtering.")
    return filtered


def _choose_buffer_crs(unioned_geom: Any):
    pyproj = _require("pyproj")
    centroid = unioned_geom.centroid
    lon = float(centroid.x)
    lat = float(centroid.y)

    if lat >= 84:
        return pyproj.CRS.from_epsg(3413)
    if lat <= -80:
        return pyproj.CRS.from_epsg(3031)
    zone = int((lon + 180.0) // 6.0) + 1
    zone = max(1, min(60, zone))
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    return pyproj.CRS.from_epsg(epsg)


def build_admin_aoi(admin_gdf, buffer_km: float = 0.0, out_crs: str = "EPSG:4326"):
    gpd = _require("geopandas")
    shapely_ops = _require("shapely.ops")

    if admin_gdf.crs is None:
        raise ValueError("Admin GeoDataFrame must have CRS.")

    admin_4326 = admin_gdf.to_crs("EPSG:4326")
    unioned = shapely_ops.unary_union(admin_4326.geometry)
    if unioned.is_empty:
        raise ValueError("Unioned admin geometry is empty.")

    if buffer_km <= 0:
        aoi = gpd.GeoDataFrame(geometry=[unioned], crs="EPSG:4326").to_crs(out_crs).geometry.iloc[0]
    else:
        work_crs = _choose_buffer_crs(unioned)
        geom_work = gpd.GeoDataFrame(geometry=[unioned], crs="EPSG:4326").to_crs(work_crs)
        buffered = geom_work.geometry.iloc[0].buffer(buffer_km * 1000.0)
        aoi = gpd.GeoDataFrame(geometry=[buffered], crs=work_crs).to_crs(out_crs).geometry.iloc[0]

    admin_geom = gpd.GeoDataFrame(geometry=[unioned], crs="EPSG:4326").to_crs(out_crs).geometry.iloc[0]
    admin_bounds = tuple(float(v) for v in admin_geom.bounds)
    aoi_bounds = tuple(float(v) for v in aoi.bounds)

    return {
        "admin_union_geom": admin_geom,
        "aoi_geom": aoi,
        "admin_bounds": admin_bounds,
        "aoi_bounds": aoi_bounds,
    }


def admin_bounds_hash(
    iso3: str,
    bounds: tuple[float, float, float, float],
    precision: int = 6,
) -> str:
    payload = {
        "iso3": _validate_iso3(iso3),
        "bounds": [round(float(v), precision) for v in bounds],
    }
    text = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def resolve_admin_level(admin_layer: str | None = None, target_adm_level: int | None = None) -> int:
    if target_adm_level is not None:
        level = int(target_adm_level)
        if level >= 0:
            return level
    if admin_layer:
        match = re.search(r"(\d+)", str(admin_layer))
        if match:
            return int(match.group(1))
    raise ValueError(
        f"Unable to resolve admin level from admin_layer={admin_layer!r}, target_adm_level={target_adm_level!r}"
    )


def admin_layer_label(adm_level: int) -> str:
    return f"admin{int(adm_level)}"


def admin_pcode_label(adm_level: int) -> str:
    return f"adm{int(adm_level)}_pcode"


def resolve_admin_pcode_column(columns: list[str] | Any, adm_level: int) -> str:
    col_names = [str(c) for c in columns]
    wanted = admin_pcode_label(adm_level).lower()
    exact = [c for c in col_names if c.lower() == wanted]
    if exact:
        return exact[0]

    pcode_cols = [c for c in col_names if c.lower().endswith("_pcode")]
    level_cols = [c for c in pcode_cols if f"adm{int(adm_level)}" in c.lower()]
    if len(level_cols) == 1:
        return level_cols[0]
    if len(level_cols) > 1:
        raise KeyError(f"Multiple admin pcode columns match admin level {adm_level}: {level_cols}")
    if len(pcode_cols) == 1:
        return pcode_cols[0]

    raise KeyError(
        f"Could not resolve admin pcode column for admin level {adm_level}. "
        f"Available columns: {col_names}"
    )
