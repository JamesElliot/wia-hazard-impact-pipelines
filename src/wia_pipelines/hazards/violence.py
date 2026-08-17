from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import RunConfig
from ..core.admin import (
    admin_layer_label,
    admin_pcode_label,
    load_admin_layer,
    resolve_admin_level,
    resolve_admin_pcode_column,
)
from ..core.aggregation import labelled_sum
from ..core.assets import checksum_path, load_admin_source_manifest, shared_cache_root
from ..core.pipeline import (
    build_admin_source,
    build_hazard_run_context,
    record_artifact,
    standardize_admin_summary,
    sync_run_metadata,
)
from ..core.progress import make_progress_writer
from .coverage_checks import check_worldpop_coverage, evaluate_coverage_gate
from .violence_visualize import write_run_maps


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
    skip_if_complete: bool = False,
) -> dict[str, Any]:
    config = inputs.to_run_config()
    return build_hazard_run_context(
        config, create_dirs=create_dirs, write_metadata=write_metadata, skip_if_complete=skip_if_complete
    )


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


def run_violence_pipeline(
    inputs: ViolenceRunInputs,
    admin_path: Path,
    worldpop_path: Path,
    acled_csv: Path | None = None,
    admin_layer: str = "admin2",
    included_event_types: list[str] | None = None,
    worldpop_coverage_min_pct: float = 98.0,
    worldpop_coverage_hard_min_pct: float = 50.0,
    mask_threshold_events: int = 1,
    all_touched: bool = True,
    skip_if_complete: bool = False,
) -> dict[str, Any]:
    import warnings

    import geopandas as gpd
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import rasterio
    from pyproj import CRS
    from rasterio.enums import MergeAlg
    from rasterio.features import rasterize
    from shapely.geometry import box
    from shapely.geometry import Point
    from shapely.ops import unary_union

    ctx = build_violence_run_context(
        inputs=inputs, create_dirs=True, write_metadata=True, skip_if_complete=skip_if_complete
    )
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

    admin_source_vintage = load_admin_source_manifest(admin_path)["vintage"]

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
        sync_run_metadata(metadata, metadata_path)

    def _add_artifact(kind: str, path: Path, note: str = "") -> None:
        record_artifact(metadata, kind, path, note)

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
    admin_stats_csv = layout["tables"] / f"{config.run_id}_{admin_label}_{admin_source_vintage}_stats.csv"
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
    # DOC-006/PROD-003: checksum WorldPop/admin inputs for reproducibility
    # provenance, matching cyclone/earthquake's existing pattern. Added as
    # sibling keys rather than restructuring admin_path/worldpop_tif into
    # nested {"path", "sha256"} dicts, since nothing else in this codebase
    # depends on the existing flat shape, but changing it anyway isn't worth
    # the risk for a metadata-only addition. cache_dir avoids re-hashing the
    # ~988MB admin file on every run in a batch.
    checksum_cache_dir = shared_cache_root(config.output_root, "checksums")
    metadata.setdefault("inputs", {})
    metadata["inputs"].update(
        {
            "admin_path": str(admin_path),
            "admin_layer": admin_layer,
            "worldpop_tif": str(worldpop_path),
            "acled_csv": str(acled_path),
            "admin_sha256": checksum_path(admin_path, cache_dir=checksum_cache_dir),
            "worldpop_sha256": checksum_path(worldpop_path, cache_dir=checksum_cache_dir),
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
        # float32, not float64: a whole-country 100m raster is large enough
        # (COL admin2 extent is ~270M pixels) that each extra float64 copy
        # downstream costs ~2GB, and several such arrays are alive at once --
        # this was reproducibly OOM-killing large-country runs (see the
        # QC-figure-3 comment below for a related, previously-patched case).
        wp_arr = src.read(1).astype("float32")
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
    admin = load_admin_layer(admin_path, layer=admin_layer)
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

    # --acled-csv may be a multi-country export (e.g. a combined COL+VEN file):
    # events are only filtered by date/event_type above, not by country. Drop
    # events far outside this run's admin bounds before the expensive
    # per-event buffer + unary_union below -- otherwise every run buffers and
    # unions every other country's events too, which is wasted work and can
    # exhaust memory on large combined exports. Padding is generous relative
    # to the largest ACLED proximity buffer (5km, see acled_buffer_km) so no
    # in-country event is at risk of being dropped.
    pad_deg = 0.2
    minx, miny, maxx, maxy = admin_bounds
    in_bounds = events_wgs84.geometry.x.between(minx - pad_deg, maxx + pad_deg) & events_wgs84.geometry.y.between(
        miny - pad_deg, maxy + pad_deg
    )
    events_wgs84 = events_wgs84.loc[in_bounds].reset_index(drop=True)
    df = df.loc[in_bounds].reset_index(drop=True)
    if events_wgs84.empty:
        raise ValueError(
            f"No ACLED events found within {config.iso3} admin bounds (+{pad_deg}deg padding) after filters."
        )

    wp_cov = check_worldpop_coverage(admin_bounds, worldpop_path)
    n_inside = int(events_wgs84.within(admin_union).sum())
    metadata["preflight_coverage"] = {
        "thresholds": {
            "worldpop_coverage_min_pct": float(worldpop_coverage_min_pct),
            "worldpop_coverage_hard_min_pct": float(worldpop_coverage_hard_min_pct),
        },
        "worldpop": wp_cov,
        "acled_events": {
            "n_events_after_filters": int(len(events_wgs84)),
            "n_events_inside_admin": int(n_inside),
            "event_bounds_4326": [float(v) for v in events_wgs84.total_bounds],
        },
    }
    wp_gate = evaluate_coverage_gate(
        wp_cov["coverage_pct"], worldpop_coverage_min_pct, worldpop_coverage_hard_min_pct
    )
    if wp_gate == "fail":
        _write_metadata()
        raise RuntimeError(
            "WorldPop coverage below hard minimum: "
            f"{wp_cov['coverage_pct']:.3f}% < {worldpop_coverage_hard_min_pct:.3f}%"
        )
    if wp_gate == "warn":
        warn_msg = (
            "WorldPop coverage below target threshold; continuing because it meets the hard minimum. "
            f"Observed={wp_cov['coverage_pct']:.3f}% Target={worldpop_coverage_min_pct:.3f}% "
            f"HardMin={worldpop_coverage_hard_min_pct:.3f}%"
        )
        warnings.warn(warn_msg, RuntimeWarning, stacklevel=2)
        metadata.setdefault("warnings", [])
        metadata["warnings"].append({"stage": "preflight_coverage", "message": warn_msg})
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
    # Kept in float32 throughout (see wp_arr load comment above): each extra
    # float64 whole-country array here previously stacked up enough
    # simultaneous peak memory to OOM-kill large-country runs. np.sum below
    # is given an explicit float64 accumulator so precision isn't lost even
    # though the arrays themselves stay float32.
    if wp_nodata is not None:
        wp_arr = np.where(wp_arr == wp_nodata, np.float32(0.0), wp_arr).astype("float32")
    affected_pop = (wp_arr * mask).astype("float32")
    pop_weighted_count = (wp_arr * event_count.astype("float32")).astype("float32")
    out_profile = wp_profile.copy()
    out_profile.update(
        dtype="float32", count=1, nodata=0, compress="deflate", tiled=True, blockxsize=512, blockysize=512
    )
    with rasterio.open(pop_affected_tif, "w", **out_profile) as dst:
        dst.write(affected_pop, 1)
    with rasterio.open(pop_weighted_count_tif, "w", **out_profile) as dst:
        dst.write(pop_weighted_count, 1)
    write_ras(4, ok=4, current="complete")

    total_pop = float(wp_arr.sum(dtype="float64"))
    affected_population = float(affected_pop.sum(dtype="float64"))
    pct_affected = (affected_population / total_pop * 100.0) if total_pop > 0 else 0.0
    pop_weighted_mean_event_count = (
        (float(pop_weighted_count.sum(dtype="float64")) / total_pop) if total_pop > 0 else 0.0
    )
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
    # No defensive copy of wp_arr here (PERF/MEM): imshow only reads its input,
    # and a full-array copy of the whole-country WorldPop raster was enough
    # extra peak memory to get this step OOM-killed on memory-constrained
    # hosts for large countries (observed reproducibly for MLI at admin2).
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.imshow(wp_arr, interpolation="nearest", extent=extent, origin="upper")
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
    # PERF-006: rasterize admin polygons once (each pixel labelled 1..n_admin)
    # instead of three separate rasterstats.zonal_stats calls, each of which
    # independently rasterizes/window-extracts the same geometries. all_touched
    # is fixed at False for all three (as it was for all three zonal_stats
    # calls before), so there's no earthquake-style double-counting pitfall
    # here (see PERF-006's earthquake entry) to worry about. wp_arr/
    # affected_pop/pop_weighted_count already have nodata zeroed out in
    # place (line ~404 above), matching each zonal_stats call's own
    # nodata-exclusion -- a zeroed-out pixel contributes nothing to a sum
    # either way, so no extra valid_mask is needed to reproduce the same
    # totals.
    write_zon = make_progress_writer(zonal_status, f"{admin_label}_zonal_stats", total=5)
    write_zon(0, current="start")
    admin_zs = admin_units.to_crs("EPSG:4326") if str(admin_units.crs).upper() != "EPSG:4326" else admin_units
    n_admin_zs = len(admin_zs)
    admin_id_zs = rasterize(
        shapes=[(geom, i + 1) for i, geom in enumerate(admin_zs.geometry)],
        out_shape=wp_arr.shape,
        transform=wp_transform,
        fill=0,
        dtype="int32",
        all_touched=False,
    )
    pop_total = np.asarray(labelled_sum(admin_id_zs, wp_arr, n_labels=n_admin_zs), dtype="float64")
    write_zon(1, ok=1, current="zonal_total_done")
    pop_aff = np.asarray(labelled_sum(admin_id_zs, affected_pop, n_labels=n_admin_zs), dtype="float64")
    write_zon(2, ok=2, current="zonal_affected_done")
    pop_weighted_sum = np.asarray(
        labelled_sum(admin_id_zs, pop_weighted_count, n_labels=n_admin_zs), dtype="float64"
    )
    write_zon(3, ok=3, current="zonal_weighted_done")
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
    admin_df = standardize_admin_summary(
        admin_df,
        config=config,
        admin_level=adm_level,
        admin_pcode_column=pcode_label,
        population_total_column="pop_total",
        population_affected_column="pop_affected",
        pct_affected_column="pct_affected",
    )
    admin_df.to_csv(admin_stats_csv, index=False)
    metadata["admin_source"] = build_admin_source(
        admin_path=admin_path,
        admin_level=adm_level,
        unit_count=len(admin_df),
        pcode_field=pcode_label,
        checksum_cache_dir=checksum_cache_dir,
    )
    write_zon(4, ok=4, current=f"{admin_label}_table_written")
    _add_artifact("admin_stats", admin_stats_csv, f"{admin_label.title()} violence population summary")

    map_paths = write_run_maps(
        admin_units,
        admin_df,
        event_count_tif,
        layout["maps"],
        iso3=config.iso3,
        pcode_column=pcode_label,
        admin_level=adm_level,
        window_start=config.window_start.isoformat(),
        window_end=config.window_end.isoformat(),
    )
    for kind, path in map_paths.items():
        _add_artifact(kind, path, f"{admin_label.title()} violence indicator map")

    metadata["admin_stats"] = {
        "admin_stats_csv": str(admin_stats_csv),
        "admin_layer": admin_layer,
        "admin_level": int(adm_level),
        "admin_pcode_column": pcode_label,
        "all_touched_admin": False,
        f"n_{admin_label}": int(len(admin_df)),
        f"{admin_label}_pop_total_sum": float(admin_df["pop_total"].sum()),
        f"{admin_label}_pop_affected_sum": float(admin_df["pop_affected"].sum()),
        f"{admin_label}_pop_weighted_event_count_sum": float(admin_df["pop_weighted_event_count_sum"].sum()),
        f"{admin_label}_pop_weighted_mean_event_count": float(
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

    # PROD-001: terminal marker so a *future* run can tell this one genuinely
    # finished (vs. the run_metadata.json build_hazard_run_context already
    # wrote at the very start of this run, before any real computation).
    metadata["status"] = "SUCCESS"
    _write_metadata()
    outputs = {
        "event_count_tif": str(event_count_tif),
        "mask_tif": str(mask_tif),
        "pop_affected_tif": str(pop_affected_tif),
        "pop_weighted_event_count_tif": str(pop_weighted_count_tif),
        "admin_stats_csv": str(admin_stats_csv),
        "qc_coverage_png": str(qc_coverage_png),
        "qc_mask_png": str(qc_mask_png),
        "qc_mask_worldpop_png": str(qc_mask_worldpop_png),
        "run_metadata": str(metadata_path),
        **{kind: str(path) for kind, path in map_paths.items()},
    }

    return {
        "run_dir": str(run_dir),
        "run_id": config.run_id,
        "outputs": outputs,
    }
