from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import rasterio
from pyproj import CRS
from shapely.geometry import GeometryCollection, box
from shapely.ops import unary_union


@dataclass(frozen=True)
class _WorldPopInfo:
    bounds_4326: tuple[float, float, float, float]
    profile: dict[str, Any]
    crs: CRS | None


def _validate_iso3(iso3: str) -> str:
    value = (iso3 or "").strip().upper()
    if len(value) != 3 or not value.isalpha():
        raise ValueError(f"iso3 must be a 3-letter country code, got '{iso3}'.")
    return value


def _validate_admin_level(target_adm_level: int) -> None:
    if target_adm_level < 0 or target_adm_level > 3:
        raise ValueError(f"target_adm_level must be between 0 and 3, got {target_adm_level}.")


def _validate_buffer(buffer_km: float) -> None:
    if buffer_km < 0:
        raise ValueError(f"buffer_km must be >= 0, got {buffer_km}.")


def _load_admin_layer(admin_path: Path, admin_layer: str | None) -> gpd.GeoDataFrame:
    if not admin_path.exists():
        raise FileNotFoundError(f"Admin dataset not found: {admin_path.resolve()}")

    try:
        return gpd.read_file(admin_path, layer=admin_layer)
    except Exception as exc:
        if admin_layer is None:
            hint = "Set admin_layer explicitly for multi-layer sources (GeoPackage/FileGDB)."
        else:
            hint = f"Check that admin_layer='{admin_layer}' exists in the source."
        raise RuntimeError(f"Failed to read admin dataset '{admin_path}': {exc}. {hint}") from exc


def _validate_fields(gdf: gpd.GeoDataFrame, iso3_field: str, adm_level_field: str | None) -> None:
    missing = [f for f in [iso3_field, adm_level_field] if f and f not in gdf.columns]
    if missing:
        raise KeyError(
            f"Missing required field(s) in admin dataset: {missing}. Available fields: {list(gdf.columns)}"
        )


def _make_valid_geometry(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.empty:
        return gdf

    gdf = gdf.copy()
    gdf = gdf[gdf.geometry.notna()]
    if gdf.empty:
        raise ValueError("Admin geometries are all empty/null after filtering.")

    try:
        gdf["geometry"] = gdf.geometry.make_valid()
    except Exception:
        gdf["geometry"] = gdf.geometry.buffer(0)

    gdf = gdf[gdf.is_valid & ~gdf.is_empty]
    if gdf.empty:
        raise ValueError("No valid geometries remain after geometry repair.")
    return gdf


def _filter_country_admin(
    gdf: gpd.GeoDataFrame,
    iso3: str,
    iso3_field: str,
    target_adm_level: int,
    adm_level_field: str | None,
) -> gpd.GeoDataFrame:
    country = gdf[gdf[iso3_field].astype(str).str.upper() == iso3].copy()
    if country.empty:
        raise ValueError(f"No records found for iso3='{iso3}' using field '{iso3_field}'.")

    if adm_level_field:
        country = country[country[adm_level_field] == target_adm_level].copy()
        if country.empty:
            raise ValueError(f"No records for iso3='{iso3}' at {adm_level_field}={target_adm_level}.")

    return country


def _choose_buffer_crs(unioned_geom: Any) -> CRS:
    centroid = unioned_geom.centroid
    lon = float(centroid.x)
    lat = float(centroid.y)

    if lat >= 84:
        return CRS.from_epsg(3413)
    if lat <= -80:
        return CRS.from_epsg(3031)

    zone = int((lon + 180.0) // 6.0) + 1
    zone = max(1, min(60, zone))
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    return CRS.from_epsg(epsg)


def _build_aoi(
    admin_gdf_4326: gpd.GeoDataFrame,
    buffer_km: float,
    out_crs: str,
) -> tuple[Any, Any, tuple[float, float, float, float]]:
    unioned = unary_union(admin_gdf_4326.geometry)
    if isinstance(unioned, GeometryCollection) and unioned.is_empty:
        raise ValueError("Unioned admin geometry is empty.")

    if buffer_km == 0:
        aoi = gpd.GeoDataFrame(geometry=[unioned], crs="EPSG:4326").to_crs(out_crs).geometry.iloc[0]
    else:
        work_crs = _choose_buffer_crs(unioned)
        unioned_gdf = gpd.GeoDataFrame(geometry=[unioned], crs="EPSG:4326").to_crs(work_crs)
        buffered = unioned_gdf.geometry.iloc[0].buffer(buffer_km * 1000.0)
        aoi = gpd.GeoDataFrame(geometry=[buffered], crs=work_crs).to_crs(out_crs).geometry.iloc[0]

    admin_out = gpd.GeoDataFrame(geometry=[unioned], crs="EPSG:4326").to_crs(out_crs).geometry.iloc[0]
    admin_bounds = tuple(float(v) for v in admin_out.bounds)
    aoi_bounds = tuple(float(v) for v in aoi.bounds)
    return admin_out, aoi, admin_bounds, aoi_bounds


def _worldpop_info(worldpop_path: Path, worldpop_band: int) -> _WorldPopInfo:
    if not worldpop_path.exists():
        raise FileNotFoundError(f"WorldPop raster not found: {worldpop_path.resolve()}")

    with rasterio.open(worldpop_path) as src:
        if worldpop_band < 1 or worldpop_band > src.count:
            raise ValueError(
                f"worldpop_band={worldpop_band} is out of range for raster with {src.count} band(s)."
            )

        profile = {
            "driver": src.driver,
            "dtype": src.dtypes[worldpop_band - 1],
            "nodata": src.nodatavals[worldpop_band - 1],
            "width": src.width,
            "height": src.height,
            "count": src.count,
            "crs": str(src.crs) if src.crs else None,
            "transform": tuple(src.transform),
            "bounds": tuple(float(v) for v in src.bounds),
        }

        raster_bounds_geom = box(*src.bounds)
        if src.crs:
            raster_bounds_4326 = (
                gpd.GeoSeries([raster_bounds_geom], crs=src.crs).to_crs("EPSG:4326").iloc[0].bounds
            )
        else:
            raster_bounds_4326 = src.bounds

        bounds = tuple(float(v) for v in raster_bounds_4326)
        return _WorldPopInfo(
            bounds_4326=bounds, profile=profile, crs=CRS.from_user_input(src.crs) if src.crs else None
        )


def _overlap_report(
    admin_bounds: tuple[float, float, float, float],
    aoi_bounds: tuple[float, float, float, float],
    worldpop_bounds: tuple[float, float, float, float] | None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "summary": "WorldPop raster not provided; overlap checks skipped.",
        "aoi_bbox_covered_pct": None,
        "aoi_fully_covered_by_worldpop": None,
        "warnings": [],
        "admin_bounds": admin_bounds,
        "aoi_bounds": aoi_bounds,
        "worldpop_bounds": worldpop_bounds,
    }

    if worldpop_bounds is None:
        return report

    aoi_bbox = box(*aoi_bounds)
    wp_bbox = box(*worldpop_bounds)
    inter = aoi_bbox.intersection(wp_bbox)

    aoi_area = aoi_bbox.area
    covered_pct = 0.0 if aoi_area == 0 else (inter.area / aoi_area) * 100.0
    fully_covered = wp_bbox.contains(aoi_bbox) or wp_bbox.equals(aoi_bbox)

    warnings: list[str] = []
    if not fully_covered:
        warnings.append("WorldPop bounds do not fully cover AOI bounds. Clip AOI or use a wider raster.")
    if covered_pct < 100.0:
        warnings.append(f"AOI bbox coverage by WorldPop bbox is {covered_pct:.2f}% (<100%).")

    summary = (
        f"AOI bbox coverage by WorldPop bbox: {covered_pct:.2f}% "
        f"(full coverage: {'yes' if fully_covered else 'no'})."
    )

    report.update(
        {
            "summary": summary,
            "aoi_bbox_covered_pct": covered_pct,
            "aoi_fully_covered_by_worldpop": fully_covered,
            "warnings": warnings,
        }
    )
    return report


def prepare_geography(
    iso3: str,
    admin_path: str,
    admin_layer: str | None = None,
    iso3_field: str = "ISO3",
    target_adm_level: int = 2,
    adm_level_field: str | None = None,
    buffer_km: float = 0.0,
    worldpop_path: str | None = None,
    worldpop_band: int = 1,
    out_crs: str = "EPSG:4326",
) -> dict[str, Any]:
    """Prepare harmonised geography inputs for hazard pipelines.

    Steps:
    1) Load admin boundaries from Shapefile/GeoPackage/FileGDB and filter by ISO3.
    2) Optionally filter to the requested admin level.
    3) Build an AOI by buffering unioned admin geometry in a projected CRS (metres).
    4) Optionally inspect WorldPop raster bounds and return overlap diagnostics.

    Returns a dictionary containing prepared geometries, bounds, overlap diagnostics,
    and suggested next processing steps.
    """
    _validate_admin_level(target_adm_level)
    _validate_buffer(buffer_km)
    iso3_norm = _validate_iso3(iso3)

    out_crs_obj = CRS.from_user_input(out_crs)

    admin_ds_path = Path(admin_path)
    raw_admin = _load_admin_layer(admin_ds_path, admin_layer)
    _validate_fields(raw_admin, iso3_field=iso3_field, adm_level_field=adm_level_field)

    admin_filtered = _filter_country_admin(
        raw_admin,
        iso3=iso3_norm,
        iso3_field=iso3_field,
        target_adm_level=target_adm_level,
        adm_level_field=adm_level_field,
    )
    admin_filtered = _make_valid_geometry(admin_filtered)

    if admin_filtered.crs is None:
        raise ValueError("Admin dataset has no CRS; set CRS on source data before calling prepare_geography.")

    admin_out_gdf = admin_filtered.to_crs(out_crs_obj)
    admin_for_union = admin_filtered.to_crs("EPSG:4326")

    admin_union_geom, aoi_geom, admin_bounds, aoi_bounds = _build_aoi(
        admin_for_union,
        buffer_km=buffer_km,
        out_crs=out_crs,
    )

    worldpop_bounds = None
    worldpop_profile = None
    worldpop_crs = None

    if worldpop_path:
        wp_info = _worldpop_info(Path(worldpop_path), worldpop_band=worldpop_band)
        worldpop_bounds = wp_info.bounds_4326
        worldpop_profile = wp_info.profile
        worldpop_crs = wp_info.crs

    overlap_report = _overlap_report(
        admin_bounds=admin_bounds,
        aoi_bounds=aoi_bounds,
        worldpop_bounds=worldpop_bounds,
    )

    needs_reproject = False
    needs_clip = False
    if worldpop_crs is not None:
        needs_reproject = worldpop_crs != out_crs_obj
    if overlap_report.get("aoi_fully_covered_by_worldpop") is not None:
        needs_clip = not bool(overlap_report["aoi_fully_covered_by_worldpop"])

    suggested_processing = {
        "needs_reproject": needs_reproject,
        "needs_clip": needs_clip,
        "notes": (
            "If needs_reproject is true, align raster and vector data to a common CRS before zonal "
            "stats. If needs_clip is true, clip AOI to available raster coverage or source a wider raster."
        ),
    }

    return {
        "admin_gdf": admin_out_gdf,
        "admin_union_geom": admin_union_geom,
        "aoi_geom": aoi_geom,
        "admin_bounds": admin_bounds,
        "aoi_bounds": aoi_bounds,
        "worldpop_bounds": worldpop_bounds,
        "worldpop_profile": worldpop_profile,
        "overlap_report": overlap_report,
        "suggested_processing": suggested_processing,
    }


def plot_geography_overview(
    admin_gdf: gpd.GeoDataFrame, aoi_geom: Any, worldpop_bounds: tuple[float, float, float, float] | None
) -> None:
    """Quick-look plot of admin geometries, AOI, and optional WorldPop bounds."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 8))
    admin_gdf.boundary.plot(ax=ax, linewidth=0.8, color="tab:blue", label="Admin")

    gpd.GeoSeries([aoi_geom], crs=admin_gdf.crs).boundary.plot(
        ax=ax, linewidth=1.5, color="tab:orange", label="AOI"
    )

    if worldpop_bounds is not None:
        wp_box = box(*worldpop_bounds)
        gpd.GeoSeries([wp_box], crs="EPSG:4326").to_crs(admin_gdf.crs).boundary.plot(
            ax=ax, linewidth=1.2, color="tab:green", linestyle="--", label="WorldPop bounds"
        )

    ax.set_title("Geography Overview")
    ax.legend()
    ax.set_aspect("equal")
    plt.tight_layout()
    plt.show()
