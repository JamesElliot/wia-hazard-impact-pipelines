from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.windows import bounds as window_bounds
from rasterio.windows import Window
from shapely import affinity
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry


@dataclass
class AggregationResult:
    table: pd.DataFrame
    country_summary: dict[str, float | None]


def _normalise_longitude_domain(geometry: BaseGeometry, raster_centre_x: float) -> BaseGeometry:
    if geometry.is_empty:
        return geometry
    centre = geometry.centroid.x
    while centre - raster_centre_x > 180:
        geometry = affinity.translate(geometry, xoff=-360)
        centre -= 360
    while raster_centre_x - centre > 180:
        geometry = affinity.translate(geometry, xoff=360)
        centre += 360
    return geometry


def _to_population_crs(
    geometry: BaseGeometry,
    population_crs,
    raster_centre_x: float,
) -> BaseGeometry:
    series = gpd.GeoSeries([geometry], crs=4326).to_crs(population_crs)
    result = series.iloc[0]
    if population_crs.is_geographic:
        result = _normalise_longitude_domain(result, raster_centre_x)
    return result


def aggregate_population(
    admin: gpd.GeoDataFrame,
    population_path: Path,
    band_geometries: Mapping[int, BaseGeometry | None],
    storm_primary_geometries: Mapping[str, BaseGeometry],
    fields: Mapping[str, str],
    primary_threshold: int,
    admin_level: int,
    mask_path: Path | None = None,
    *,
    all_touched_population: bool = False,
    all_touched_admin: bool = False,
    chunk_size: int = 1024,
) -> AggregationResult:
    with rasterio.open(population_path) as source:
        if source.count != 1:
            raise ValueError("WorldPop input must contain exactly one raster band")
        if source.crs is None:
            raise ValueError("WorldPop input has no CRS")
        crs = source.crs
        centre_x = (source.bounds.left + source.bounds.right) / 2
        admin_pop = admin.to_crs(crs).reset_index(drop=True)
        if crs.is_geographic:
            admin_pop.geometry = admin_pop.geometry.map(
                lambda geom: _normalise_longitude_domain(geom, centre_x)
            )
        admin_spatial_index = admin_pop.sindex
        projected_bands = {
            int(threshold): (
                None if geometry is None or geometry.is_empty else _to_population_crs(geometry, crs, centre_x)
            )
            for threshold, geometry in band_geometries.items()
        }
        n_admin = len(admin_pop)
        totals = np.zeros(n_admin, dtype=np.float64)
        affected = {threshold: np.zeros(n_admin, dtype=np.float64) for threshold in projected_bands}
        weighted_wind = np.zeros(n_admin, dtype=np.float64)
        population_raster_total = 0.0

        destination = None
        if mask_path is not None:
            output_profile = source.profile.copy()
            output_profile.update(
                count=len(projected_bands),
                dtype="uint8",
                nodata=0,
                compress="deflate",
                predictor=1,
                BIGTIFF="IF_SAFER",
            )
            destination = rasterio.open(mask_path, "w", **output_profile)
            for band_index, threshold in enumerate(sorted(projected_bands), start=1):
                destination.set_band_description(band_index, f"wind_ge_{threshold}_kmh")

        try:
            for row_off in range(0, source.height, chunk_size):
                height = min(chunk_size, source.height - row_off)
                for col_off in range(0, source.width, chunk_size):
                    width = min(chunk_size, source.width - col_off)
                    window = Window(col_off, row_off, width, height)
                    transform = source.window_transform(window)
                    raw = source.read(1, window=window, masked=True)
                    population = np.asarray(raw.filled(0), dtype=np.float64)
                    population[~np.isfinite(population) | (population < 0)] = 0
                    population_raster_total += float(population.sum())
                    left, bottom, right, top = window_bounds(window, source.transform)
                    admin_indices = admin_spatial_index.query(
                        box(left, bottom, right, top), predicate="intersects"
                    )
                    admin_shapes = [
                        (admin_pop.geometry.iloc[index], int(index) + 1)
                        for index in admin_indices
                        if not admin_pop.geometry.iloc[index].is_empty
                    ]
                    labels = (
                        rasterize(
                            admin_shapes,
                            out_shape=(height, width),
                            transform=transform,
                            fill=0,
                            dtype="int32",
                            all_touched=all_touched_admin,
                        )
                        if admin_shapes
                        else np.zeros((height, width), dtype=np.int32)
                    )
                    totals += np.bincount(labels.ravel(), weights=population.ravel(), minlength=n_admin + 1)[
                        1:
                    ]
                    severity = np.zeros((height, width), dtype=np.float32)
                    for band_index, threshold in enumerate(sorted(projected_bands), start=1):
                        geometry = projected_bands[threshold]
                        mask = (
                            np.zeros((height, width), dtype=np.uint8)
                            if geometry is None
                            else rasterize(
                                [(geometry, 1)],
                                out_shape=(height, width),
                                transform=transform,
                                fill=0,
                                dtype="uint8",
                                all_touched=all_touched_population,
                            )
                        )
                        affected[threshold] += np.bincount(
                            labels.ravel(),
                            weights=(population * mask).ravel(),
                            minlength=n_admin + 1,
                        )[1:]
                        severity[mask == 1] = float(threshold)
                        if destination is not None:
                            destination.write(mask, band_index, window=window)
                    weighted_wind += np.bincount(
                        labels.ravel(),
                        weights=(population * severity).ravel(),
                        minlength=n_admin + 1,
                    )[1:]
        finally:
            if destination is not None:
                destination.close()

    admin_4326 = admin.to_crs(4326).reset_index(drop=True)
    storm_counts = np.zeros(n_admin, dtype=np.int32)
    for geometry in storm_primary_geometries.values():
        if geometry is None or geometry.is_empty:
            continue
        for index, admin_geometry in enumerate(admin_4326.geometry):
            adjusted = _normalise_longitude_domain(geometry, admin_geometry.centroid.x)
            if adjusted.intersects(admin_geometry):
                storm_counts[index] += 1

    if primary_threshold not in affected:
        raise ValueError("Primary threshold is missing from band geometries")
    primary = primary_threshold
    identifiers = {
        f"adm{level}_pcode": _field(admin, fields, f"adm{level}_pcode") for level in range(admin_level + 1)
    }
    identifiers[f"adm{admin_level}_name_en"] = _field(admin, fields, f"adm{admin_level}_name_en")
    identifiers[f"adm{admin_level}_name_local"] = _field(admin, fields, f"adm{admin_level}_name_local")
    rows = pd.DataFrame(
        {
            **identifiers,
            "pop_total": totals,
            "pop_affected": affected[primary],
            "storm_count": storm_counts,
        }
    )
    rows["pct_affected"] = np.divide(
        affected[primary] * 100,
        totals,
        out=np.full(n_admin, np.nan),
        where=totals > 0,
    )
    rows["popwtd_maxwind_kmh"] = np.divide(
        weighted_wind,
        totals,
        out=np.full(n_admin, np.nan),
        where=totals > 0,
    )
    for threshold in sorted(affected):
        rows[f"pct_affected_{threshold}"] = np.divide(
            affected[threshold] * 100,
            totals,
            out=np.full(n_admin, np.nan),
            where=totals > 0,
        )
    total_population = float(totals.sum())
    country_affected = float(affected[primary].sum())
    summary = {
        "pop_total": total_population,
        "pop_affected": country_affected,
        "pct_affected": country_affected / total_population * 100 if total_population else None,
        "population_raster_total": population_raster_total,
        "population_assigned_fraction": (
            total_population / population_raster_total if population_raster_total else None
        ),
    }
    return AggregationResult(rows, summary)


def _field(admin: gpd.GeoDataFrame, fields: Mapping[str, str], key: str) -> pd.Series:
    column = fields.get(key)
    if column and column in admin.columns:
        return admin[column].reset_index(drop=True)
    return pd.Series([None] * len(admin))
