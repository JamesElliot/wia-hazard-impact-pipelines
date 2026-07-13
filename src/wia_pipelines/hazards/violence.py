from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from ..config import RunConfig, initialize_run_metadata, validate_run_metadata
from ..core.admin import admin_layer_label, admin_pcode_label, resolve_admin_level, resolve_admin_pcode_column
from ..core.io_paths import build_run_layout, create_run_dirs, write_json
from .coverage_checks import check_worldpop_coverage


@dataclass(frozen=True)
class ViolenceRunInputs:
    iso3: str
    as_of_date: str
    lookback_months: int = 12
    output_root: Path = Path("./outputs")
    target_adm_level: int = 2
    buffer_km: float = 0.0

    def to_run_config(self) -> RunConfig:
        return RunConfig(
            hazard="violence",
            iso3=self.iso3,
            as_of_date=self.as_of_date,
            lookback_months=self.lookback_months,
            output_root=self.output_root,
            target_adm_level=self.target_adm_level,
            buffer_km=self.buffer_km,
        )


def build_violence_run_context(
    inputs: ViolenceRunInputs,
    create_dirs: bool = True,
    write_metadata: bool = True,
) -> dict[str, Any]:
    config = inputs.to_run_config()
    layout = build_run_layout(
        output_root=config.output_root,
        hazard="violence",
        iso3=config.iso3,
        run_id=config.run_id,
    )
    if create_dirs:
        create_run_dirs(layout)

    metadata = initialize_run_metadata(config, paths=layout)
    metadata["pipeline"] = "violence_acled_proximity"
    validate_run_metadata(metadata)

    metadata_path = layout["base"] / "run_metadata.json"
    if write_metadata:
        write_json(metadata_path, metadata)

    return {
        "config": config,
        "layout": layout,
        "metadata": metadata,
        "metadata_path": metadata_path,
    }


def acled_buffer_km(event_type: str, fatalities: float) -> int:
    event_type = (event_type or "").strip()
    f = float(fatalities or 0.0)
    if event_type == "Battles":
        return 5
    if event_type == "Explosions/Remote violence":
        return 5
    if event_type == "Violence against civilians":
        return 5 if f >= 1 else 2
    if event_type == "Riots":
        return 2
    if event_type == "Protests":
        return 1
    raise ValueError(f"Unsupported ACLED event_type for proximity buffer: '{event_type}'")


def make_progress_writer(status_path: Path, stage: str, total: int):
    status_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = perf_counter()
    total = max(0, int(total))

    def _write(processed: int, ok: int = 0, failed: int = 0, current: str | None = None) -> dict[str, Any]:
        processed_i = max(0, int(processed))
        elapsed = perf_counter() - started_at
        rate = (processed_i / elapsed) if elapsed > 0 else 0.0
        remaining = max(0, total - processed_i)
        eta = remaining / rate if rate > 0 else None
        payload = {
            "stage": stage,
            "processed": processed_i,
            "total": total,
            "ok": int(ok),
            "failed": int(failed),
            "pct_complete": (float(processed_i) / float(total) * 100.0) if total else 100.0,
            "elapsed_seconds": round(float(elapsed), 2),
            "rate_items_per_second": round(float(rate), 4),
            "eta_seconds": None if eta is None else round(float(eta), 2),
            "current": current,
        }
        status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    return _write


DEFAULT_SUPPORTED_EVENT_TYPES = (
    "Battles",
    "Explosions/Remote violence",
    "Violence against civilians",
    "Riots",
    "Protests",
)
DEFAULT_INCLUDED_EVENT_TYPES = (
    "Battles",
    "Explosions/Remote violence",
    "Violence against civilians",
    "Riots",
)


def _resolve_acled_csv_default(iso3: str, window_start: str, window_end: str) -> Path:
    default_name = f"acled_{iso3.lower()}_{window_start.replace('-', '')}-{window_end.replace('-', '')}.csv"
    default_path = Path("./data/violence") / default_name
    if default_path.exists():
        return default_path
    # Legacy fallback patterns from older notebook naming.
    legacy = [
        Path("./data/violence") / f"acled_{iso3.lower()}_{window_start.replace('-', '')}_{window_end}.csv",
        Path("./data/violence")
        / f"acled_{iso3.lower()}_{window_start.replace('-', '')}_{window_end.replace('-', '')}.csv",
    ]
    for p in legacy:
        if p.exists():
            return p
    candidates = sorted((Path("./data/violence")).glob(f"acled_{iso3.lower()}_*.csv"))
    if candidates:
        return candidates[-1]
    return default_path


def _load_admin(admin_path: Path, layer: str):
    import geopandas as gpd

    if str(admin_path).lower().endswith(".zip"):
        return gpd.read_file(f"zip://{admin_path.resolve()}", layer=layer)
    try:
        return gpd.read_file(admin_path, layer=layer)
    except Exception:
        return gpd.read_file(admin_path)


def run_violence_pipeline(
    inputs: ViolenceRunInputs,
    admin_path: Path,
    worldpop_path: Path,
    acled_csv: Path | None = None,
    admin_layer: str = "admin2",
    included_event_types: list[str] | None = None,
    worldpop_coverage_min_pct: float = 98.0,
    mask_threshold_events: int = 1,
    all_touched: bool = True,
) -> dict[str, Any]:
    import geopandas as gpd
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import rasterio
    from pyproj import CRS
    from rasterio.enums import MergeAlg
    from rasterio.features import rasterize
    from shapely.geometry import box
    from rasterstats import zonal_stats
    from shapely.geometry import Point
    from shapely.ops import unary_union

    ctx = build_violence_run_context(inputs=inputs, create_dirs=True, write_metadata=True)
    config = ctx["config"]
    layout = ctx["layout"]
    metadata = ctx["metadata"]
    metadata_path: Path = ctx["metadata_path"]

    acled_path = acled_csv or _resolve_acled_csv_default(
        iso3=config.iso3,
        window_start=config.window_start.isoformat(),
        window_end=config.window_end.isoformat(),
    )
    if not admin_path.exists():
        raise FileNotFoundError(f"Missing admin boundaries: {admin_path}")
    if not worldpop_path.exists():
        raise FileNotFoundError(f"Missing WorldPop raster: {worldpop_path}")
    if not acled_path.exists():
        raise FileNotFoundError(f"Missing ACLED CSV: {acled_path}")

    selected_types = (
        list(included_event_types) if included_event_types else list(DEFAULT_INCLUDED_EVENT_TYPES)
    )
    if not selected_types:
        raise ValueError("included_event_types cannot be empty.")
    unknown_types = sorted(set(selected_types) - set(DEFAULT_SUPPORTED_EVENT_TYPES))
    if unknown_types:
        raise ValueError(
            f"included_event_types contains unsupported values: {unknown_types}. "
            f"Supported: {sorted(DEFAULT_SUPPORTED_EVENT_TYPES)}"
        )

    def _write_metadata() -> None:
        validate_run_metadata(metadata)
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    def _add_artifact(kind: str, path: Path, note: str = "") -> None:
        metadata.setdefault("artifacts", [])
        metadata["artifacts"].append({"kind": kind, "path": str(path), "notes": note})

    adm_level = resolve_admin_level(admin_layer, config.target_adm_level)
    admin_label = admin_layer_label(adm_level)
    pcode_label = admin_pcode_label(adm_level)

    # Paths
    run_dir = layout["base"]
    qc_dir = layout["qc"] / "violence"
    qc_dir.mkdir(parents=True, exist_ok=True)
    qc_coverage_png = qc_dir / f"{config.run_id}_coverage_check.png"
    qc_mask_png = qc_dir / f"{config.run_id}_mask.png"
    qc_mask_worldpop_png = qc_dir / f"{config.run_id}_mask_on_worldpop.png"
    event_count_tif = layout["rasters"] / "violence" / f"{config.run_id}_violence_event_count.tif"
    mask_tif = layout["rasters"] / "violence" / f"{config.run_id}_violence_mask.tif"
    pop_affected_tif = layout["rasters"] / "violence" / f"{config.run_id}_violence_pop_affected.tif"
    pop_weighted_count_tif = (
        layout["rasters"] / "violence" / f"{config.run_id}_violence_pop_weighted_event_count.tif"
    )
    footprint_gpkg = layout["intermediate"] / "violence" / f"{config.run_id}_violence_footprint.gpkg"
    admin_stats_csv = layout["tables"] / f"{config.run_id}_{admin_label}_stats.csv"
    for p in [
        event_count_tif,
        mask_tif,
        pop_affected_tif,
        pop_weighted_count_tif,
        footprint_gpkg,
        admin_stats_csv,
    ]:
        p.parent.mkdir(parents=True, exist_ok=True)

    buffer_status = layout["logs"] / "violence_buffer_status.json"
    raster_status = layout["logs"] / "violence_raster_status.json"
    zonal_status = layout["logs"] / "violence_zonal_status.json"

    metadata["pipeline"] = "violence_acled_proximity"
    metadata["violence_config"] = {
        "pipeline": "violence_acled_proximity",
        "supported_event_types": list(DEFAULT_SUPPORTED_EVENT_TYPES),
        "included_event_types": selected_types,
    }
    metadata.setdefault("inputs", {})
    metadata["inputs"].update(
        {
            "admin_path": str(admin_path),
            "admin_layer": admin_layer,
            "worldpop_tif": str(worldpop_path),
            "acled_csv": str(acled_path),
        }
    )
    metadata.setdefault("paths", {})
    metadata["paths"]["status_files"] = {
        "buffer": str(buffer_status),
        "raster": str(raster_status),
        "zonal": str(zonal_status),
    }

    # Load WorldPop
    with rasterio.open(worldpop_path) as src:
        wp_profile = src.profile.copy()
        wp_crs = src.crs
        wp_transform = src.transform
        wp_height, wp_width = src.height, src.width
        wp_nodata = src.nodata
        wp_bounds = src.bounds
        wp_arr = src.read(1).astype("float64")
    metadata["worldpop_ref"] = {
        "crs": str(wp_crs),
        "shape": [int(wp_height), int(wp_width)],
        "nodata": None if wp_nodata is None else float(wp_nodata),
    }

    # Load/filter ACLED
    raw_df = pd.read_csv(acled_path)
    req = ["latitude", "longitude", "event_date", "event_type"]
    missing = [c for c in req if c not in raw_df.columns]
    if missing:
        raise ValueError(f"Missing required ACLED columns: {missing}")
    df = raw_df.copy()
    df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce")
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df["fatalities"] = pd.to_numeric(df.get("fatalities", 0), errors="coerce").fillna(0)
    df = df.dropna(subset=["event_date", "latitude", "longitude", "event_type"]).copy()
    df = df[df["latitude"].between(-90, 90) & df["longitude"].between(-180, 180)].copy()
    df = df[
        (df["event_date"] >= pd.Timestamp(config.window_start))
        & (df["event_date"] <= pd.Timestamp(config.window_end))
    ]
    df = df[df["event_type"].isin(selected_types)].copy()
    if df.empty:
        raise ValueError("No ACLED events remain after filters.")
    df["buffer_km"] = [acled_buffer_km(t, f) for t, f in zip(df["event_type"], df["fatalities"])]
    events_wgs84 = gpd.GeoDataFrame(
        df,
        geometry=[Point(xy) for xy in zip(df["longitude"], df["latitude"])],
        crs="EPSG:4326",
    )

    # Admin and preflight
    admin = _load_admin(admin_path, layer=admin_layer)
    if "iso3" not in admin.columns:
        raise KeyError("Admin layer must include 'iso3' column.")
    source_pcode_col = resolve_admin_pcode_column(admin.columns, adm_level)
    admin_units = admin[admin["iso3"] == config.iso3].copy()
    admin_units = (
        admin_units.dropna(subset=[source_pcode_col, "geometry"]).to_crs("EPSG:4326").reset_index(drop=True)
    )
    if admin_units.empty:
        raise ValueError(f"No admin features found for ISO3={config.iso3}.")
    admin_units = admin_units.rename(columns={source_pcode_col: pcode_label})
    admin_union = admin_units.geometry.union_all()
    admin_bounds = tuple(float(v) for v in admin_units.total_bounds)
    wp_cov = check_worldpop_coverage(admin_bounds, worldpop_path)
    n_inside = int(events_wgs84.within(admin_union).sum())
    metadata["preflight_coverage"] = {
        "thresholds": {"worldpop_coverage_min_pct": float(worldpop_coverage_min_pct)},
        "worldpop": wp_cov,
        "acled_events": {
            "n_events_after_filters": int(len(events_wgs84)),
            "n_events_inside_admin": int(n_inside),
            "event_bounds_4326": [float(v) for v in events_wgs84.total_bounds],
        },
    }
    if float(wp_cov["coverage_pct"]) < float(worldpop_coverage_min_pct):
        raise RuntimeError(
            f"WorldPop coverage below threshold: {wp_cov['coverage_pct']:.3f}% < {worldpop_coverage_min_pct:.3f}%"
        )
    if n_inside < 1:
        raise RuntimeError("No filtered ACLED events intersect admin boundaries.")

    # QC figure 1: coverage check (admin + events + admin/worldpop bounds)
    fig, ax = plt.subplots(figsize=(6, 6))
    admin_units.boundary.plot(ax=ax, linewidth=0.6, edgecolor="black", alpha=0.8)
    events_wgs84.plot(ax=ax, markersize=6, color="tab:red", alpha=0.6)
    gpd.GeoSeries([box(*admin_bounds)], crs="EPSG:4326").boundary.plot(
        ax=ax, linewidth=1.0, edgecolor="tab:blue", linestyle="--", alpha=0.8
    )
    gpd.GeoSeries([box(*wp_cov["worldpop_bounds_4326"])], crs="EPSG:4326").boundary.plot(
        ax=ax, linewidth=1.0, edgecolor="tab:green", linestyle=":", alpha=0.9
    )
    ax.set_title(f"{config.iso3} coverage check")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    plt.tight_layout()
    fig.savefig(qc_coverage_png, dpi=150)
    plt.close(fig)
    _add_artifact("qc_coverage", qc_coverage_png, "Coverage check: admin, events, worldpop bounds")

    # Buffer and footprint
    centroid = events_wgs84.union_all().centroid
    utm_zone = int((centroid.x + 180) // 6) + 1
    epsg = 32600 + utm_zone if centroid.y >= 0 else 32700 + utm_zone
    events_m = events_wgs84.to_crs(CRS.from_epsg(epsg))
    metadata["buffering"] = {
        "method": "utm_from_event_centroid",
        "buffer_crs_epsg": int(epsg),
        "utm_zone": int(utm_zone),
    }

    write_buf = make_progress_writer(buffer_status, "buffer_union", total=len(events_m))
    write_buf(0, current="start")
    buffered_geoms_m = []
    for i, (geom, km) in enumerate(
        zip(events_m.geometry.values, events_m["buffer_km"].to_numpy(dtype=float)), start=1
    ):
        buffered_geoms_m.append(geom.buffer(float(km) * 1000.0))
        if i % max(1, len(events_m) // 20) == 0 or i == len(events_m):
            write_buf(i, ok=i, current=f"buffered_{i}")
    buffered_geoms_wgs84 = list(gpd.GeoSeries(buffered_geoms_m, crs=events_m.crs).to_crs("EPSG:4326").values)
    footprint_m = unary_union(buffered_geoms_m)
    footprint_wgs84 = gpd.GeoDataFrame(
        {"run_id": [config.run_id], "n_events": [int(len(events_m))]},
        geometry=[footprint_m],
        crs=events_m.crs,
    ).to_crs("EPSG:4326")
    footprint_wgs84.to_file(footprint_gpkg, driver="GPKG")
    _add_artifact("violence_footprint", footprint_gpkg, "Unioned ACLED footprint")
    metadata["footprint"] = {
        "footprint_gpkg": str(footprint_gpkg),
        "n_events": int(len(events_m)),
        "buffer_km_counts": df["buffer_km"].value_counts().sort_index().to_dict(),
    }
    write_buf(len(events_m), ok=len(events_m), current="complete")

    # Rasterization: event count and binary mask
    write_ras = make_progress_writer(raster_status, "rasterize_event_count_and_mask", total=4)
    write_ras(0, current="start")
    event_count = rasterize(
        ((g, 1) for g in buffered_geoms_wgs84),
        out_shape=(wp_height, wp_width),
        transform=wp_transform,
        fill=0,
        dtype="uint32",
        merge_alg=MergeAlg.add,
        all_touched=all_touched,
    )
    write_ras(1, ok=1, current="event_count_ready")

    count_profile = wp_profile.copy()
    count_profile.update(
        dtype="uint32", count=1, nodata=0, compress="deflate", tiled=True, blockxsize=512, blockysize=512
    )
    with rasterio.open(event_count_tif, "w", **count_profile) as dst:
        dst.write(event_count, 1)
    write_ras(2, ok=2, current="event_count_written")

    mask = (event_count >= int(mask_threshold_events)).astype("uint8")
    mask_profile = wp_profile.copy()
    mask_profile.update(
        dtype="uint8", count=1, nodata=0, compress="deflate", tiled=True, blockxsize=512, blockysize=512
    )
    with rasterio.open(mask_tif, "w", **mask_profile) as dst:
        dst.write(mask, 1)
    write_ras(3, ok=3, current="mask_written")

    # Population rasters
    if wp_nodata is not None:
        wp_arr = np.where(wp_arr == wp_nodata, 0.0, wp_arr)
    affected_pop = wp_arr * mask
    pop_weighted_count = wp_arr * event_count.astype("float64")
    out_profile = wp_profile.copy()
    out_profile.update(
        dtype="float32", count=1, nodata=0, compress="deflate", tiled=True, blockxsize=512, blockysize=512
    )
    with rasterio.open(pop_affected_tif, "w", **out_profile) as dst:
        dst.write(affected_pop.astype("float32"), 1)
    with rasterio.open(pop_weighted_count_tif, "w", **out_profile) as dst:
        dst.write(pop_weighted_count.astype("float32"), 1)
    write_ras(4, ok=4, current="complete")

    total_pop = float(wp_arr.sum())
    affected_population = float(affected_pop.sum())
    pct_affected = (affected_population / total_pop * 100.0) if total_pop > 0 else 0.0
    pop_weighted_mean_event_count = (float(pop_weighted_count.sum()) / total_pop) if total_pop > 0 else 0.0
    _add_artifact("event_count", event_count_tif, "Buffered ACLED event count")
    _add_artifact("hazard_mask", mask_tif, "Binary hazard mask from event count threshold")
    _add_artifact("pop_affected_raster", pop_affected_tif, "WorldPop x binary mask")
    _add_artifact("pop_weighted_event_count_raster", pop_weighted_count_tif, "WorldPop x event count")
    metadata["hazard_intensity"] = {
        "event_count_tif": str(event_count_tif),
        "dtype": "uint32",
        "max_event_count": int(event_count.max()),
        "all_touched": bool(all_touched),
    }
    metadata["hazard_mask"] = {
        "mask_tif": str(mask_tif),
        "dtype": "uint8",
        "threshold_metric": "event_count",
        "threshold_value": int(mask_threshold_events),
        "affected_pixels": int(mask.sum()),
        "total_pixels": int(mask.size),
    }
    metadata["population_impact"] = {
        "affected_pop_tif": str(pop_affected_tif),
        "pop_weighted_event_count_tif": str(pop_weighted_count_tif),
        "total_population": total_pop,
        "affected_population": affected_population,
        "pct_population_affected": pct_affected,
        "pop_weighted_mean_event_count": pop_weighted_mean_event_count,
    }

    # QC figure 2: binary mask
    extent = (wp_bounds.left, wp_bounds.right, wp_bounds.bottom, wp_bounds.top)
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.imshow(mask, interpolation="nearest", extent=extent, origin="upper")
    admin_units.boundary.plot(ax=ax, linewidth=0.5, edgecolor="black", alpha=0.8)
    ax.set_title(f"{config.iso3} violence mask (>= {int(mask_threshold_events)} events)")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    plt.tight_layout()
    fig.savefig(qc_mask_png, dpi=150)
    plt.close(fig)
    _add_artifact("qc_mask", qc_mask_png, "Binary violence mask")

    # QC figure 3: mask on WorldPop
    wp_plot = wp_arr.copy()
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.imshow(wp_plot, interpolation="nearest", extent=extent, origin="upper")
    ax.imshow(
        np.where(mask == 1, 1, np.nan), interpolation="nearest", extent=extent, origin="upper", alpha=0.35
    )
    admin_units.boundary.plot(ax=ax, linewidth=0.5, edgecolor="black", alpha=0.8)
    ax.set_title(f"{config.iso3} violence mask on WorldPop")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    plt.tight_layout()
    fig.savefig(qc_mask_worldpop_png, dpi=150)
    plt.close(fig)
    _add_artifact("qc_mask_worldpop", qc_mask_worldpop_png, "Violence mask overlay on WorldPop")

    # Admin zonal stats.
    write_zon = make_progress_writer(zonal_status, f"{admin_label}_zonal_stats", total=5)
    write_zon(0, current="start")
    admin_zs = admin_units.to_crs("EPSG:4326") if str(admin_units.crs).upper() != "EPSG:4326" else admin_units
    zs_total = zonal_stats(
        admin_zs, str(worldpop_path), stats=["sum"], nodata=wp_nodata, all_touched=all_touched
    )
    write_zon(1, ok=1, current="zonal_total_done")
    zs_aff = zonal_stats(admin_zs, str(pop_affected_tif), stats=["sum"], nodata=0, all_touched=all_touched)
    write_zon(2, ok=2, current="zonal_affected_done")
    zs_weighted = zonal_stats(
        admin_zs, str(pop_weighted_count_tif), stats=["sum"], nodata=0, all_touched=all_touched
    )
    write_zon(3, ok=3, current="zonal_weighted_done")

    pop_total = np.array([r["sum"] if r["sum"] is not None else 0.0 for r in zs_total], dtype="float64")
    pop_aff = np.array([r["sum"] if r["sum"] is not None else 0.0 for r in zs_aff], dtype="float64")
    pop_weighted_sum = np.array(
        [r["sum"] if r["sum"] is not None else 0.0 for r in zs_weighted], dtype="float64"
    )
    pct_aff = np.where(pop_total > 0, pop_aff / pop_total * 100.0, np.nan)
    pop_weighted_mean = np.where(pop_total > 0, pop_weighted_sum / pop_total, np.nan)
    admin_df = pd.DataFrame(
        {
            "iso3": config.iso3,
            pcode_label: admin_zs[pcode_label].astype(str).values,
            "pop_total": pop_total,
            "pop_affected": pop_aff,
            "pct_affected": pct_aff,
            "pop_weighted_event_count_sum": pop_weighted_sum,
            "pop_weighted_mean_event_count": pop_weighted_mean,
        }
    )
    admin_df.to_csv(admin_stats_csv, index=False)
    write_zon(4, ok=4, current=f"{admin_label}_table_written")
    _add_artifact("admin_stats", admin_stats_csv, f"{admin_label.title()} violence population summary")
    _add_artifact(
        f"{admin_label}_stats", admin_stats_csv, f"{admin_label.title()} violence population summary"
    )
    if adm_level == 2:
        _add_artifact("adm2_stats", admin_stats_csv, "ADM2 violence population summary")
    metadata["admin_stats"] = {
        "admin_stats_csv": str(admin_stats_csv),
        "admin_layer": admin_layer,
        "admin_level": int(adm_level),
        "admin_pcode_column": pcode_label,
        f"n_{admin_label}": int(len(admin_df)),
        f"{admin_label}_pop_total_sum": float(admin_df["pop_total"].sum()),
        f"{admin_label}_pop_affected_sum": float(admin_df["pop_affected"].sum()),
        f"{admin_label}_pop_weighted_event_count_sum": float(admin_df["pop_weighted_event_count_sum"].sum()),
        f"{admin_label}_pop_weighted_mean_event_count": float(
            admin_df["pop_weighted_event_count_sum"].sum() / max(admin_df["pop_total"].sum(), 1.0)
        ),
    }
    metadata[f"{admin_label}_stats"] = dict(metadata["admin_stats"])
    if adm_level == 2:
        metadata["adm2_stats"] = {
            "adm2_stats_csv": str(admin_stats_csv),
            "n_adm2": int(len(admin_df)),
            "adm2_pop_total_sum": float(admin_df["pop_total"].sum()),
            "adm2_pop_affected_sum": float(admin_df["pop_affected"].sum()),
            "adm2_pop_weighted_event_count_sum": float(admin_df["pop_weighted_event_count_sum"].sum()),
            "adm2_pop_weighted_mean_event_count": float(
                admin_df["pop_weighted_event_count_sum"].sum() / max(admin_df["pop_total"].sum(), 1.0)
            ),
        }
    metadata["acled_events"] = {
        "rows_loaded": int(len(raw_df)),
        "rows_after_filter": int(len(df)),
        "window_start": config.window_start.isoformat(),
        "window_end": config.window_end.isoformat(),
        "included_event_types": selected_types,
        "event_type_counts": df["event_type"].value_counts().to_dict(),
        "buffer_km_counts": df["buffer_km"].value_counts().sort_index().to_dict(),
    }
    metadata["qc_outputs"] = {
        "coverage_check_png": str(qc_coverage_png),
        "mask_png": str(qc_mask_png),
        "mask_on_worldpop_png": str(qc_mask_worldpop_png),
    }
    write_zon(5, ok=5, current="complete")

    _write_metadata()
    outputs = {
        "event_count_tif": str(event_count_tif),
        "mask_tif": str(mask_tif),
        "pop_affected_tif": str(pop_affected_tif),
        "pop_weighted_event_count_tif": str(pop_weighted_count_tif),
        "admin_stats_csv": str(admin_stats_csv),
        f"{admin_label}_stats_csv": str(admin_stats_csv),
        "qc_coverage_png": str(qc_coverage_png),
        "qc_mask_png": str(qc_mask_png),
        "qc_mask_worldpop_png": str(qc_mask_worldpop_png),
        "run_metadata": str(metadata_path),
    }
    if adm_level == 2:
        outputs["adm2_stats_csv"] = str(admin_stats_csv)

    return {
        "run_dir": str(run_dir),
        "run_id": config.run_id,
        "outputs": outputs,
    }
