from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from ..config import RunConfig
from ..core.pipeline import (
    build_hazard_run_context,
    record_artifact,
    standardize_admin_summary,
    sync_run_metadata,
)
from .coverage_checks import check_worldpop_coverage


@dataclass(frozen=True)
class FloodRunInputs:
    iso3: str
    as_of_date: str
    lookback_months: int = 12
    output_root: Path = Path("./outputs")
    target_adm_level: int = 2
    buffer_km: float = 0.0

    def to_run_config(self) -> RunConfig:
        return RunConfig(
            hazard="flood",
            iso3=self.iso3,
            as_of_date=self.as_of_date,
            lookback_months=self.lookback_months,
            output_root=self.output_root,
            target_adm_level=self.target_adm_level,
            buffer_km=self.buffer_km,
        )


def build_flood_run_context(
    inputs: FloodRunInputs,
    create_dirs: bool = True,
    write_metadata: bool = True,
) -> dict[str, Any]:
    config = inputs.to_run_config()
    return build_hazard_run_context(config, create_dirs=create_dirs, write_metadata=write_metadata)


def flood_binary_from_days(flood_days, threshold_days: int = 0):
    """Return uint8 binary mask where days > threshold."""
    threshold = int(threshold_days)
    if threshold < 0:
        raise ValueError(f"threshold_days must be >= 0, got {threshold_days}.")
    return (flood_days > threshold).astype("uint8")


def evaluate_preflight_coverage(
    worldpop_coverage_pct: float,
    flood_stac_union_coverage_pct: float,
    worldpop_min_pct: float = 98.0,
    flood_min_pct: float = 99.999,
) -> dict[str, Any]:
    wp_ok = float(worldpop_coverage_pct) >= float(worldpop_min_pct)
    flood_ok = float(flood_stac_union_coverage_pct) >= float(flood_min_pct)
    return {
        "worldpop_ok": bool(wp_ok),
        "flood_stac_ok": bool(flood_ok),
        "ok": bool(wp_ok and flood_ok),
        "thresholds": {
            "worldpop_min_pct": float(worldpop_min_pct),
            "flood_stac_union_min_pct": float(flood_min_pct),
        },
        "observed": {
            "worldpop_coverage_pct": float(worldpop_coverage_pct),
            "flood_stac_union_coverage_pct": float(flood_stac_union_coverage_pct),
        },
    }


def make_progress_writer(
    status_path: Path,
    stage: str,
    total: int,
):
    """Build a lightweight closure that writes JSON progress snapshots."""
    status_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = perf_counter()
    total = max(0, int(total))

    def _write(processed: int, ok: int = 0, failed: int = 0, current: str | None = None) -> dict[str, Any]:
        processed_i = max(0, int(processed))
        elapsed = perf_counter() - started_at
        rate = (processed_i / elapsed) if elapsed > 0 else 0.0
        remaining = max(0, total - processed_i)
        eta_seconds = (remaining / rate) if rate > 0 else None
        payload = {
            "stage": stage,
            "processed": processed_i,
            "total": total,
            "ok": int(ok),
            "failed": int(failed),
            "pct_complete": (float(processed_i) / float(total) * 100.0) if total else 100.0,
            "elapsed_seconds": round(float(elapsed), 2),
            "rate_items_per_second": round(float(rate), 4),
            "eta_seconds": None if eta_seconds is None else round(float(eta_seconds), 2),
            "current": current,
        }
        status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    return _write


def close_enough(a: float, b: float, atol: float = 1e-3, rtol: float = 1e-7) -> bool:
    return math.isclose(a, b, abs_tol=atol, rel_tol=rtol)


def group_stac_items_by_day(items) -> dict[str, list]:
    """Group STAC acquisitions by UTC calendar day for flooded-day counting."""

    grouped: dict[str, list] = {}
    for item in items:
        value = item.properties.get("datetime")
        if not value:
            raise ValueError(f"STAC item {item.id!r} has no datetime property.")
        grouped.setdefault(str(value)[:10], []).append(item)
    return dict(sorted(grouped.items()))


@dataclass(frozen=True)
class FloodPipelineRunOptions:
    inputs: FloodRunInputs
    admin_path: Path
    worldpop_path: Path
    admin_layer: str = "admin2"
    iso3_field: str = "iso3"
    stac_api_url: str = "https://stac.eodc.eu/api/v1"
    collection_id: str = "GFM"
    asset_key: str = "ensemble_flood_extent"
    datetime_range: str | None = None
    worldpop_coverage_min_pct: float = 98.0
    flood_stac_coverage_min_pct: float = 99.999
    flood_stac_coverage_hard_min_pct: float = 50.0
    flood_binary_threshold_days: int = 0
    chunk_y: int = 1024
    chunk_x: int = 1024


def run_flood_pipeline(options: FloodPipelineRunOptions) -> dict[str, Any]:
    import numpy as np
    import pandas as pd
    import rasterio
    from odc.geo.geobox import GeoBox
    from odc.stac import load as stac_load
    from pystac_client import Client
    from rasterio.features import rasterize
    from shapely.geometry import box, mapping
    from shapely.ops import unary_union

    from ..core.admin import (
        admin_bounds_hash,
        admin_layer_label,
        admin_pcode_label,
        filter_admin_for_iso3,
        load_admin_layer,
        resolve_admin_level,
        resolve_admin_pcode_column,
    )
    from ..core.aggregation import labelled_sum
    from ..core.raster_ops import reproject_array_to_grid, write_array_geotiff

    inputs = options.inputs
    if not options.admin_path.exists():
        raise FileNotFoundError(f"Admin boundaries not found: {options.admin_path}")
    if not options.worldpop_path.exists():
        raise FileNotFoundError(f"WorldPop raster not found: {options.worldpop_path}")
    if int(options.flood_binary_threshold_days) < 0:
        raise ValueError("flood_binary_threshold_days must be >= 0")
    if (
        float(options.flood_stac_coverage_hard_min_pct) < 0.0
        or float(options.flood_stac_coverage_hard_min_pct) > 100.0
    ):
        raise ValueError("flood_stac_coverage_hard_min_pct must be within [0, 100]")
    if float(options.flood_stac_coverage_min_pct) < float(options.flood_stac_coverage_hard_min_pct):
        raise ValueError("flood_stac_coverage_min_pct must be >= flood_stac_coverage_hard_min_pct")

    ctx = build_flood_run_context(inputs=inputs, create_dirs=True, write_metadata=True)
    config = ctx["config"]
    layout = ctx["layout"]
    metadata = ctx["metadata"]
    metadata_path = ctx["metadata_path"]
    iso3 = config.iso3

    def _sync() -> None:
        sync_run_metadata(metadata, metadata_path)

    def _artifact(kind: str, path: Path, note: str = "") -> None:
        record_artifact(metadata, kind, path, note)

    adm_level = resolve_admin_level(options.admin_layer, config.target_adm_level)
    admin_label = admin_layer_label(adm_level)
    pcode_label = admin_pcode_label(adm_level)

    # Admin and bounds.
    admin_all = load_admin_layer(options.admin_path, layer=options.admin_layer)
    admin_gdf = filter_admin_for_iso3(admin_all, iso3=iso3, iso3_field=options.iso3_field)
    admin_4326 = admin_gdf.to_crs("EPSG:4326")
    country_geom = admin_4326.geometry.union_all()
    west, south, east, north = tuple(float(v) for v in country_geom.bounds)
    admin_bounds_wsen = (west, south, east, north)
    bounds_hash = admin_bounds_hash(iso3, admin_bounds_wsen)
    bounds_hash_path = layout["logs"] / "aoi_bounds_hash.txt"
    bounds_hash_path.write_text(bounds_hash, encoding="utf-8")
    _artifact("aoi_bounds_hash", bounds_hash_path, "Admin bounds hash for flood run")

    # WorldPop reference.
    with rasterio.open(options.worldpop_path) as wp:
        wp_arr = wp.read(1).astype("float32")
        wp_transform = wp.transform
        wp_crs = wp.crs
        wp_shape = (wp.height, wp.width)
        wp_nodata = wp.nodata
        wp_bounds = wp.bounds
        wp_res = wp.res
    pop_valid = np.isfinite(wp_arr)
    if wp_nodata is not None:
        pop_valid &= wp_arr != float(wp_nodata)
    pop_valid &= wp_arr >= 0
    _artifact("worldpop_raster", options.worldpop_path, "WorldPop grid for flood aggregation")

    window_start = config.window_start.isoformat()
    window_end = config.window_end.isoformat()
    flood_native_dir = layout["rasters"] / "flood"
    flood_native_dir.mkdir(parents=True, exist_ok=True)
    flood_days_tif = flood_native_dir / f"{iso3}_flood_days_{window_start}_{window_end}.tif"
    reused_existing_flood_days = flood_days_tif.exists()

    # STAC search and preflight.
    if options.datetime_range:
        datetime_range = options.datetime_range
    else:
        datetime_range = (
            f"{config.window_start.isoformat()}T00:00:00Z/{config.window_end.isoformat()}T23:59:59Z"
        )
    wp_cov = check_worldpop_coverage(admin_bounds_wsen, options.worldpop_path)

    wp_ok = float(wp_cov.get("coverage_pct", 0.0)) >= float(options.worldpop_coverage_min_pct)
    if not wp_ok:
        _sync()
        raise RuntimeError(
            f"WorldPop coverage below threshold: {wp_cov.get('coverage_pct', 0.0):.3f}% < {options.worldpop_coverage_min_pct:.3f}%"
        )

    items = []
    item_ids: list[str] = []
    failures: list[dict[str, str]] = []
    success = 0
    failed = 0
    flood_nodata = 255
    union_cov: float | None = None
    if reused_existing_flood_days:
        _artifact(
            "flood_days_tif", flood_days_tif, "Reused existing flood severity raster: days flooded per pixel"
        )
        metadata["preflight_coverage"] = {
            "worldpop": wp_cov,
            "thresholds": {
                "worldpop_coverage_min_pct": float(options.worldpop_coverage_min_pct),
                "flood_stac_union_coverage_min_pct": float(options.flood_stac_coverage_min_pct),
                "flood_stac_union_coverage_hard_min_pct": float(options.flood_stac_coverage_hard_min_pct),
            },
            "flood_stac": {
                "datetime_range": datetime_range,
                "reused_existing_flood_days": True,
                "flood_days_tif": str(flood_days_tif),
            },
        }
    else:
        client = Client.open(options.stac_api_url)
        search = client.search(
            collections=[options.collection_id],
            intersects=mapping(country_geom),
            datetime=datetime_range,
            limit=1000,
            fields={
                "include": [
                    "id",
                    "type",
                    "stac_version",
                    "collection",
                    "links",
                    "bbox",
                    "geometry",
                    "properties.datetime",
                    f"assets.{options.asset_key}",
                ]
            },
        )
        items = [it for it in search.items() if options.asset_key in it.assets and it.bbox is not None]
        if not items:
            raise RuntimeError(
                f"No STAC items found for {iso3} with asset {options.asset_key} in {datetime_range}"
            )

        admin_box = box(*admin_bounds_wsen)
        item_bboxes = [box(*it.bbox) for it in items]
        item_ids = [it.id for it in items]
        item_cov = []
        for ib in item_bboxes:
            inter = admin_box.intersection(ib)
            cov = 0.0 if admin_box.area == 0 else float((inter.area / admin_box.area) * 100.0)
            item_cov.append(cov)
        union_bbox = unary_union(item_bboxes)
        union_inter = admin_box.intersection(union_bbox)
        union_cov = 0.0 if admin_box.area == 0 else float((union_inter.area / admin_box.area) * 100.0)
        union_full = bool(union_cov >= float(options.flood_stac_coverage_min_pct))

        metadata["preflight_coverage"] = {
            "worldpop": wp_cov,
            "thresholds": {
                "worldpop_coverage_min_pct": float(options.worldpop_coverage_min_pct),
                "flood_stac_union_coverage_min_pct": float(options.flood_stac_coverage_min_pct),
                "flood_stac_union_coverage_hard_min_pct": float(options.flood_stac_coverage_hard_min_pct),
            },
            "flood_stac": {
                "item_count": int(len(items)),
                "item_ids": item_ids,
                "item_bbox_coverages_pct": [float(v) for v in item_cov],
                "union_bbox_coverage_pct": float(union_cov),
                "union_full_coverage": bool(union_full),
                "union_above_hard_min": bool(union_cov >= float(options.flood_stac_coverage_hard_min_pct)),
                "datetime_range": datetime_range,
            },
        }
        if float(union_cov) < float(options.flood_stac_coverage_hard_min_pct):
            _sync()
            raise RuntimeError(
                "Flood STAC union coverage below hard minimum: "
                f"{union_cov:.3f}% < {options.flood_stac_coverage_hard_min_pct:.3f}%"
            )
        if not union_full:
            warn_msg = (
                "Flood STAC union coverage below target threshold; continuing because it meets hard minimum. "
                f"Observed={union_cov:.3f}% Target={options.flood_stac_coverage_min_pct:.3f}% "
                f"HardMin={options.flood_stac_coverage_hard_min_pct:.3f}%"
            )
            warnings.warn(warn_msg, RuntimeWarning, stacklevel=2)
            metadata.setdefault("warnings", [])
            metadata["warnings"].append({"stage": "preflight_coverage", "message": warn_msg})

    # Streaming flood-days accumulation on worldpop-intersection window.
    win_left = max(west, float(wp_bounds.left))
    win_right = min(east, float(wp_bounds.right))
    win_bottom = max(south, float(wp_bounds.bottom))
    win_top = min(north, float(wp_bounds.top))
    if win_left >= win_right or win_bottom >= win_top:
        _sync()
        raise RuntimeError("Admin bounds do not intersect WorldPop bounds.")

    geobox_wp = GeoBox.from_bbox(
        bbox=(win_left, win_bottom, win_right, win_top),
        crs=wp_crs,
        resolution=float(abs(wp_res[0])),
        tight=True,
    )

    daily_items = group_stac_items_by_day(items) if items else {}
    status_path = layout["logs"] / f"{iso3}_cell7_status.json"
    if not reused_existing_flood_days:
        progress = make_progress_writer(
            status_path,
            stage="flood_days_streaming",
            total=len(daily_items),
        )
        progress(processed=0, ok=0, failed=0, current=None)
        flood_days_accum = None

        for idx, (day, day_items) in enumerate(daily_items.items(), start=1):
            try:
                ds_i = stac_load(
                    day_items,
                    bands=[options.asset_key],
                    geobox=geobox_wp,
                    chunks={"y": int(options.chunk_y), "x": int(options.chunk_x)},
                    dtype="uint8",
                    fail_on_error=False,
                )
                if options.asset_key in ds_i.data_vars:
                    da_i = ds_i[options.asset_key]
                elif len(ds_i.data_vars) > 0:
                    da_i = ds_i[list(ds_i.data_vars)[0]]
                else:
                    raise RuntimeError("No data variables returned by stac_load.")
                if success == 0:
                    flood_nodata = int(da_i.attrs.get("nodata", 255))
                observed_flood = (da_i != flood_nodata) & (da_i > 0)
                hit = (
                    observed_flood.any(dim="time").astype("uint16")
                    if "time" in observed_flood.dims
                    else observed_flood.astype("uint16")
                )
                hit_np = np.asarray(hit.compute().values, dtype="uint16")
                if flood_days_accum is None:
                    flood_days_accum = np.zeros(hit_np.shape, dtype="uint16")
                flood_days_accum += hit_np
                success += 1
            except Exception as exc:  # pragma: no cover - network/data runtime instability
                failed += 1
                failures.append(
                    {
                        "day": day,
                        "item_count": str(len(day_items)),
                        "error": str(exc),
                    }
                )
            progress(processed=idx, ok=success, failed=failed, current=day)

        if flood_days_accum is None:
            _sync()
            raise RuntimeError("No flood items were successfully processed.")

        # Write flood-days native raster.
        flood_days_native = flood_days_accum.astype("uint16")
        native_transform = geobox_wp.transform
        native_crs = geobox_wp.crs
        write_array_geotiff(
            flood_days_tif,
            flood_days_native,
            transform=native_transform,
            crs=native_crs,
            nodata=0,
            dtype="uint16",
        )
        _artifact("flood_days_tif", flood_days_tif, "Flood severity raster: days flooded per pixel")

    # Align to worldpop grid and derive binary mask.
    days_aligned = False
    with rasterio.open(flood_days_tif) as src_days:
        days_arr = src_days.read(1).astype("uint16")
        same_shape = (src_days.height, src_days.width) == wp_shape
        same_crs = str(src_days.crs) == str(wp_crs)
        same_transform = (
            hasattr(src_days.transform, "almost_equals")
            and hasattr(wp_transform, "almost_equals")
            and src_days.transform.almost_equals(wp_transform, precision=1e-9)
        )
        days_aligned = bool(same_shape and same_crs and same_transform)
        if not days_aligned:
            days_arr = reproject_array_to_grid(
                src_array=days_arr,
                src_transform=src_days.transform,
                src_crs=src_days.crs,
                dst_shape=wp_shape,
                dst_transform=wp_transform,
                dst_crs=wp_crs,
                src_nodata=0,
                dst_nodata=0,
                resampling="nearest",
            ).astype("uint16")
    flood_binary = flood_binary_from_days(
        days_arr, threshold_days=int(options.flood_binary_threshold_days)
    ).astype("uint8")

    flood_mask_tif = flood_native_dir / f"{iso3}_flood_any_{window_start}_{window_end}.tif"
    write_array_geotiff(
        flood_mask_tif,
        flood_binary,
        transform=wp_transform,
        crs=wp_crs,
        nodata=0,
        dtype="uint8",
    )
    _artifact(
        "flood_mask_tif",
        flood_mask_tif,
        f"Binary flood mask derived from flood_days > {int(options.flood_binary_threshold_days)}",
    )

    # Population affected + weighted days.
    pop_dir = layout["rasters"] / "pop_exposed" / "flood"
    pop_dir.mkdir(parents=True, exist_ok=True)
    pop_tif = pop_dir / f"{iso3}_pop_affected_flood_any_{window_start}_{window_end}.tif"
    pop_weighted_days_tif = pop_dir / f"{iso3}_pop_weighted_flood_days_{window_start}_{window_end}.tif"
    pop_affected = np.zeros(wp_shape, dtype="float32")
    flooded = flood_binary == 1
    pop_affected[flooded & pop_valid] = wp_arr[flooded & pop_valid]
    pop_weighted_days = np.zeros(wp_shape, dtype="float32")
    pop_weighted_days[pop_valid] = wp_arr[pop_valid] * days_arr[pop_valid].astype("float32")
    write_array_geotiff(
        pop_tif, pop_affected, transform=wp_transform, crs=wp_crs, nodata=0.0, dtype="float32"
    )
    write_array_geotiff(
        pop_weighted_days_tif,
        pop_weighted_days,
        transform=wp_transform,
        crs=wp_crs,
        nodata=0.0,
        dtype="float32",
    )
    _artifact("flood_pop_affected_tif", pop_tif, "Flood exposed population raster")
    _artifact("flood_pop_weighted_days_tif", pop_weighted_days_tif, "Population-weighted flood-days raster")

    # Admin aggregation.
    admin_units = admin_gdf.copy()
    source_pcode_col = resolve_admin_pcode_column(admin_units.columns, adm_level)
    admin_units = admin_units[[source_pcode_col, "geometry"]].dropna().reset_index(drop=True)
    admin_units_wp = admin_units.to_crs(wp_crs).rename(columns={source_pcode_col: pcode_label})
    shapes = [(geom, i + 1) for i, geom in enumerate(admin_units_wp.geometry)]
    admin_id = rasterize(
        shapes=shapes,
        out_shape=wp_shape,
        transform=wp_transform,
        fill=0,
        dtype="int32",
        all_touched=False,
    )
    n_admin = len(admin_units_wp)
    pop_total_by_id = np.asarray(
        labelled_sum(admin_id, wp_arr, n_labels=n_admin, valid_mask=pop_valid), dtype="float64"
    )
    aff_ok = np.isfinite(pop_affected) & (pop_affected >= 0) & pop_valid
    pop_aff_by_id = np.asarray(
        labelled_sum(admin_id, pop_affected, n_labels=n_admin, valid_mask=aff_ok), dtype="float64"
    )

    flat_id = admin_id.ravel()
    valid_cells = (flat_id > 0) & pop_valid.ravel()
    flat_days = days_arr.ravel().astype("float32")
    valid_days = valid_cells & np.isfinite(flat_days)
    days_sum_by_id = np.bincount(
        flat_id[valid_days], weights=flat_days[valid_days], minlength=len(admin_units_wp) + 1
    )
    days_count_by_id = np.bincount(flat_id[valid_days], minlength=len(admin_units_wp) + 1)
    days_max_by_id = np.zeros(len(admin_units_wp) + 1, dtype="float32")
    np.maximum.at(days_max_by_id, flat_id[valid_days], flat_days[valid_days])

    ids = np.arange(1, n_admin + 1, dtype=int)
    out = {
        pcode_label: admin_units_wp[pcode_label].values,
        "pop_total": pop_total_by_id,
        "pop_affected_flood": pop_aff_by_id.astype("float32"),
        "flood_days_mean": np.where(
            days_count_by_id[ids] > 0,
            days_sum_by_id[ids] / days_count_by_id[ids],
            np.nan,
        ).astype("float32"),
        "flood_days_max": days_max_by_id[ids].astype("float32"),
    }

    out_df = pd.DataFrame(out)
    out_df["pct_affected_flood"] = np.where(
        out_df["pop_total"] > 0,
        (out_df["pop_affected_flood"] / out_df["pop_total"]) * 100.0,
        np.nan,
    )
    out_df = standardize_admin_summary(
        out_df,
        config=config,
        admin_level=adm_level,
        admin_pcode_column=pcode_label,
        population_total_column="pop_total",
        population_affected_column="pop_affected_flood",
        pct_affected_column="pct_affected_flood",
    )
    out_csv = layout["tables"] / f"{iso3}_{admin_label}_flood_exposure_{window_start}_{window_end}.csv"
    out_df.to_csv(out_csv, index=False)
    _artifact("admin_flood_table", out_csv, f"{admin_label.title()} flood exposure + severity table")
    _artifact(f"{admin_label}_flood_table", out_csv, f"{admin_label.title()} flood exposure + severity table")
    if adm_level == 2:
        _artifact("admin2_flood_table", out_csv, "Admin2 flood exposure + severity table")

    # Metadata fields used by parity checks.
    metadata["gfm_load"] = {
        "manifest_hash": bounds_hash,
        "worldpop_window_bounds_epsg4326": {
            "west": float(win_left),
            "south": float(win_bottom),
            "east": float(win_right),
            "north": float(win_top),
        },
        "worldpop_window_shape": [int(wp_shape[0]), int(wp_shape[1])],
        "chunks": {"y": int(options.chunk_y), "x": int(options.chunk_x)},
        "flood_nodata": int(flood_nodata),
        "severity_metric": "flood_days_sum",
        "binary_threshold_days": int(options.flood_binary_threshold_days),
        "streaming_mode": True,
        "items_total": int(len(items)),
        "days_total": int(len(daily_items)),
        "items_success": int(success),
        "items_failed": int(failed),
        "status_file": str(status_path),
        "failures_preview": failures[-10:],
        "reused_existing_flood_days": bool(reused_existing_flood_days),
    }
    metadata["flood_mask"] = {
        "days_tif": str(flood_days_tif),
        "mask_tif": str(flood_mask_tif),
        "binary_threshold_days": int(options.flood_binary_threshold_days),
    }
    total_pop = float(wp_arr[pop_valid].sum())
    affected_pop = float(pop_affected.sum())
    metadata["flood_pop_affected"] = {
        "pop_tif": str(pop_tif),
        "pop_weighted_days_tif": str(pop_weighted_days_tif),
        "worldpop_path": str(options.worldpop_path),
        "worldpop_nodata": float(wp_nodata) if wp_nodata is not None else None,
        "worldpop_shape": [int(wp_shape[0]), int(wp_shape[1])],
        "worldpop_crs": str(wp_crs),
        "days_path": str(flood_days_tif),
        "mask_path": str(flood_mask_tif),
        "days_aligned_to_worldpop": bool(days_aligned),
        "binary_threshold_days": int(options.flood_binary_threshold_days),
        "total_pop_valid_sum": total_pop,
        "pop_affected_sum": affected_pop,
        "pop_affected_pct": (affected_pop / total_pop * 100.0) if total_pop > 0 else None,
        "max_flood_days": int(days_arr.max()),
        "mean_flood_days_flooded_cells": float(days_arr[flood_binary == 1].mean())
        if int((flood_binary == 1).sum()) > 0
        else 0.0,
    }
    metadata["admin_flood_table"] = {
        "path": str(out_csv),
        "admin_layer": options.admin_layer,
        "admin_level": int(adm_level),
        "admin_pcode_column": pcode_label,
        f"n_{admin_label}": int(len(out_df)),
        "worldpop_path": str(options.worldpop_path),
        "pop_affected_flood_tif": str(pop_tif),
        "flood_days_tif": str(flood_days_tif),
        "binary_threshold_days": int(options.flood_binary_threshold_days),
        "flood_days_aligned_to_worldpop": bool(days_aligned),
        "window_start": window_start,
        "window_end": window_end,
    }
    metadata[f"{admin_label}_flood_table"] = dict(metadata["admin_flood_table"])
    if adm_level == 2:
        metadata["admin2_flood_table"] = dict(metadata["admin_flood_table"])
    _sync()

    outputs = {
        "admin_table": str(out_csv),
        f"{admin_label}_table": str(out_csv),
        "flood_days_tif": str(flood_days_tif),
        "flood_mask_tif": str(flood_mask_tif),
        "pop_affected_tif": str(pop_tif),
    }
    if adm_level == 2:
        outputs["admin2_table"] = str(out_csv)

    return {
        "status": "SUCCESS",
        "run_dir": str(layout["base"]),
        "run_id": config.run_id,
        "metadata_path": str(metadata_path),
        "outputs": outputs,
    }
