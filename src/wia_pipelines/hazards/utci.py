from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import RunConfig
from ..core.admin import admin_bounds_hash, filter_admin_for_iso3, load_admin_layer
from ..core.assets import checksum_path, shared_cache_root
from ..core.cds import months_for_last_n
from ..core.pipeline import (
    build_admin_source,
    build_hazard_run_context,
    record_artifact,
    standardize_admin_summary,
    sync_run_metadata,
)
from ..core.progress import make_progress_writer
from .coverage_checks import check_worldpop_coverage, evaluate_coverage_gate, run_cds_single_month_check
from .coverage_requests import utci_sample_request
from .utci_visualize import write_run_maps


@dataclass(frozen=True)
class UtciRunInputs:
    iso3: str
    as_of_date: str
    lookback_months: int = 12
    output_root: Path = Path("./outputs")
    target_adm_level: int = 2
    buffer_km: float = 0.0

    def to_run_config(self) -> RunConfig:
        return RunConfig(
            hazard="heat",
            iso3=self.iso3,
            as_of_date=self.as_of_date,
            lookback_months=self.lookback_months,
            output_root=self.output_root,
            target_adm_level=self.target_adm_level,
            buffer_km=self.buffer_km,
        )


def build_utci_run_context(
    inputs: UtciRunInputs,
    create_dirs: bool = True,
    write_metadata: bool = True,
    skip_if_complete: bool = False,
) -> dict[str, Any]:
    config = inputs.to_run_config()
    return build_hazard_run_context(
        config, create_dirs=create_dirs, write_metadata=write_metadata, skip_if_complete=skip_if_complete
    )


@dataclass(frozen=True)
class UtciPipelineRunOptions:
    inputs: UtciRunInputs
    admin_path: Path
    worldpop_path: Path
    admin_layer: str = "admin2"
    iso3_field: str = "iso3"
    cds_buffer_deg: float = 0.25
    abs_thresholds_c: tuple[float, ...] = (32.0, 38.0, 46.0)
    default_reporting_threshold_c: float = 32.0
    k_consecutive_days: int = 3
    require_full_preflight_coverage: bool = True
    preflight_coverage_hard_min_pct: float = 50.0
    skip_if_complete: bool = False


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _append_artifact(metadata: dict[str, Any], kind: str, path: Path, note: str = "") -> None:
    record_artifact(metadata, kind, path, note)


def _find_daily_max_utci(ds):
    # Prefer explicit max-like variable names.
    vars_lower = {v.lower(): v for v in ds.data_vars}
    candidates = [vars_lower[k] for k in vars_lower if "utci" in k]
    if not candidates:
        candidates = [v for v in ds.data_vars if v.lower() != "crs"]
    if not candidates:
        raise ValueError(f"No data variable found in UTCI dataset: vars={list(ds.data_vars)}")
    max_like = [v for v in candidates if "max" in v.lower() or "maximum" in v.lower()]
    if max_like:
        return ds[sorted(max_like, key=len)[0]]

    base_var = sorted(candidates, key=len)[0]
    da = ds[base_var]
    stat_dims = [d for d in da.dims if d.lower() in {"statistic", "statistics", "stat", "quantile"}]
    if stat_dims:
        sd = stat_dims[0]
        coord_vals = da[sd].astype(str).values.tolist()
        matches = [i for i, s in enumerate(coord_vals) if "max" in str(s).lower()]
        if matches:
            return da.isel({sd: matches[0]}).drop_vars(sd, errors="ignore")
    return da


def _to_celsius_if_needed(da):
    import numpy as np

    sample = da.isel({da.dims[0]: 0}).mean(skipna=True).compute()
    try:
        v = float(sample.values)
    except Exception:
        return da
    if np.isfinite(v) and v > 100.0:
        da = da - 273.15
        da.attrs["units"] = "C"
    return da


def _transform_from_latlon_centers(lat_vals, lon_vals):
    import numpy as np
    import rasterio

    lat_vals = np.asarray(lat_vals, dtype="float64")
    lon_vals = np.asarray(lon_vals, dtype="float64")
    dlat = float(np.abs(np.diff(lat_vals).mean()))
    dlon = float(np.abs(np.diff(lon_vals).mean()))
    west = float(np.min(lon_vals) - dlon / 2.0)
    north = float(np.max(lat_vals) + dlat / 2.0)
    return rasterio.transform.from_origin(west, north, dlon, dlat)


def _consecutive_k_exceedance(exceed_bool_da, k: int):
    rolling_hits = exceed_bool_da.astype("int16").rolling(time=int(k), min_periods=int(k)).sum()
    return (rolling_hits >= int(k)).any(dim="time")


def run_utci_pipeline(options: UtciPipelineRunOptions) -> dict[str, Any]:
    import calendar
    import numpy as np
    import pandas as pd
    import rasterio
    import xarray as xr
    from rasterio.features import rasterize

    from ..core.cds import download_month_with_fallback, ensure_downloads, extract_zip_to_dir
    from ..core.aggregation import labelled_sum
    from ..core.raster_ops import reproject_array_to_grid, write_array_geotiff

    inputs = options.inputs
    iso3 = inputs.iso3.upper()
    if not options.admin_path.exists():
        raise FileNotFoundError(f"Admin boundaries not found: {options.admin_path}")
    if not options.worldpop_path.exists():
        raise FileNotFoundError(f"WorldPop raster not found: {options.worldpop_path}")
    if int(options.k_consecutive_days) < 1:
        raise ValueError(f"k_consecutive_days must be >=1, got {options.k_consecutive_days}")

    ctx = build_utci_run_context(
        inputs=inputs, create_dirs=True, write_metadata=True, skip_if_complete=options.skip_if_complete
    )
    config = ctx["config"]
    layout = ctx["layout"]
    metadata = ctx["metadata"]
    metadata_path = ctx["metadata_path"]

    def _sync() -> None:
        sync_run_metadata(metadata, metadata_path)

    from ..core.admin import (
        admin_layer_label,
        admin_pcode_label,
        resolve_admin_level,
        resolve_admin_pcode_column,
    )

    adm_level = resolve_admin_level(options.admin_layer, config.target_adm_level)
    admin_label = admin_layer_label(adm_level)
    pcode_label = admin_pcode_label(adm_level)

    # Admin + AOI.
    admin_all = load_admin_layer(options.admin_path, layer=options.admin_layer)
    admin_gdf = filter_admin_for_iso3(admin_all, iso3=iso3, iso3_field=options.iso3_field)
    admin_4326 = admin_gdf.to_crs("EPSG:4326")
    country_geom = admin_4326.geometry.union_all()
    west, south, east, north = tuple(float(v) for v in country_geom.bounds)
    west_b = max(-180.0, west - float(options.cds_buffer_deg))
    south_b = max(-90.0, south - float(options.cds_buffer_deg))
    east_b = min(180.0, east + float(options.cds_buffer_deg))
    north_b = min(90.0, north + float(options.cds_buffer_deg))
    cds_bbox = [north_b, west_b, south_b, east_b]
    bounds_hash = admin_bounds_hash(iso3, (west_b, south_b, east_b, north_b))
    bounds_hash_path = layout["logs"] / "aoi_bounds_hash.txt"
    bounds_hash_path.write_text(bounds_hash, encoding="utf-8")
    _append_artifact(metadata, "aoi_bounds_hash", bounds_hash_path, "AOI hash for UTCI CDS request area")

    # WorldPop reference raster.
    with rasterio.open(options.worldpop_path) as wp:
        wp_arr = wp.read(1).astype("float64")
        wp_profile = wp.profile.copy()
        wp_transform = wp.transform
        wp_crs = wp.crs
        wp_shape = (wp.height, wp.width)
        wp_nodata = wp.nodata
    wp_profile.update(count=1)
    pop_valid = np.isfinite(wp_arr)
    if wp_nodata is not None:
        pop_valid &= wp_arr != float(wp_nodata)
    pop_valid &= wp_arr >= 0
    _append_artifact(metadata, "worldpop_raster", options.worldpop_path, "WorldPop reference grid")
    # DOC-006/PROD-003: checksum WorldPop/admin inputs for reproducibility
    # provenance, matching cyclone/earthquake's existing "inputs" shape.
    # cache_dir avoids re-hashing the ~988MB admin file on every run in a batch.
    checksum_cache_dir = shared_cache_root(config.output_root, "checksums")
    metadata["inputs"] = {
        "worldpop": {
            "path": str(Path(options.worldpop_path).resolve()),
            "sha256": checksum_path(options.worldpop_path, cache_dir=checksum_cache_dir),
        },
        "admin": {
            "path": str(Path(options.admin_path).resolve()),
            "sha256": checksum_path(options.admin_path, cache_dir=checksum_cache_dir),
        },
    }
    metadata["admin_source"] = build_admin_source(
        admin_path=options.admin_path,
        admin_level=adm_level,
        unit_count=len(admin_gdf),
        pcode_field=pcode_label,
        checksum_cache_dir=checksum_cache_dir,
    )

    # Preflight.
    sample_year = int(pd.to_datetime(config.window_start.isoformat()).year)
    sample_month = int(pd.to_datetime(config.window_start.isoformat()).month)
    wp_cov = check_worldpop_coverage((west, south, east, north), options.worldpop_path)
    # PERF-002: shared with batch/preflight.py's own CDS sample cache, keyed
    # by (iso3, dataset, year, month, cds-bounds hash) so a batch preflight
    # run whose fixed sample month coincides with this run's own first
    # window month is reused instead of re-fetched -- the bounds hash keeps
    # this safe even if preflight's admin path/buffer ever diverges from
    # this run's, since a mismatched geography just misses the cache rather
    # than silently returning a sample for the wrong bounding box.
    sample_zip = (
        shared_cache_root(config.output_root, "cds_preflight_samples")
        / f"{iso3}_utci_{sample_year}{sample_month:02d}_{bounds_hash[:12]}.zip"
    )
    sample_zip.parent.mkdir(parents=True, exist_ok=True)
    sample = run_cds_single_month_check(
        dataset="derived-utci-historical",
        request=utci_sample_request(sample_year, sample_month, cds_bbox),
        output_zip=sample_zip,
    )
    if not sample["ok"] or sample.get("sample_bounds_4326") is None:
        raise RuntimeError(f"UTCI preflight sample failed: {sample.get('error')}")
    from ..core.worldpop import bbox_coverage_report

    utci_cov = bbox_coverage_report((west, south, east, north), tuple(sample["sample_bounds_4326"]))
    metadata["preflight_coverage"] = {
        "sample_year": sample_year,
        "sample_month": sample_month,
        "worldpop": wp_cov,
        "utci_sample": {
            **sample,
            "coverage_pct": float(utci_cov["coverage_pct"]),
            "full_coverage": bool(utci_cov["full_coverage"]),
        },
    }
    if options.require_full_preflight_coverage:
        sample_gate = evaluate_coverage_gate(
            utci_cov["coverage_pct"], target_pct=100.0, hard_min_pct=options.preflight_coverage_hard_min_pct
        )
        if sample_gate == "warn":
            warn_msg = (
                "UTCI preflight coverage below target (100%); continuing because it meets the hard minimum. "
                f"Observed={utci_cov['coverage_pct']:.3f}% HardMin={options.preflight_coverage_hard_min_pct:.3f}%"
            )
            warnings.warn(warn_msg, RuntimeWarning, stacklevel=2)
            metadata.setdefault("warnings", [])
            metadata["warnings"].append({"stage": "preflight_coverage", "message": warn_msg})
        elif sample_gate == "fail":
            _sync()
            raise RuntimeError(f"UTCI preflight coverage not full ({utci_cov['coverage_pct']:.3f}%).")

    # Download recent months with consolidated->intermediate fallback.
    dl_status = layout["logs"] / "utci_recent_download_status.json"
    months = months_for_last_n(config.as_of_date, n_months=config.lookback_months)
    manifest: list[dict[str, Any]] = []
    download_writer = make_progress_writer(dl_status, "utci_recent_download", len(months))

    cache_dir = Path(config.output_root).resolve() / "_cache" / "heat" / iso3 / "cds_raw"
    extract_dir = cache_dir / "extracted"
    cache_dir.mkdir(parents=True, exist_ok=True)
    extract_dir.mkdir(parents=True, exist_ok=True)
    download_writer(0, ok=0, failed=0, current=None)
    n_ok = 0
    n_fail = 0

    def _utci_cds_request(year: int, month: int, tier: str) -> dict[str, Any]:
        days = [f"{d:02d}" for d in range(1, calendar.monthrange(year, month)[1] + 1)]
        return {
            "variable": ["universal_thermal_climate_index_daily_statistics"],
            "version": "1_1",
            "product_type": tier,
            "year": [str(year)],
            "month": [f"{month:02d}"],
            "day": days,
            "area": cds_bbox,
        }

    for idx, (y, m) in enumerate(months, start=1):
        base = f"{iso3}_utci_{bounds_hash}_{y}{m:02d}"
        cons_zip = cache_dir / f"{base}_consolidated_dataset.zip"
        int_zip = cache_dir / f"{base}_intermediate_dataset.zip"
        month_ok, month_rows = download_month_with_fallback(
            "derived-utci-historical",
            _utci_cds_request,
            cons_zip,
            int_zip,
            "product_type",
            y,
            m,
        )
        manifest.extend(month_rows)

        if month_ok:
            n_ok += 1
        else:
            n_fail += 1
        download_writer(idx, ok=n_ok, failed=n_fail, current=f"{y}-{m:02d}")

    mpath = ensure_downloads(manifest=manifest, kind="utci_recent", logs_dir=layout["logs"])
    _append_artifact(metadata, "cds_manifest_utci_recent", mpath, f"{len(manifest)} UTCI requests")
    ok_df = pd.DataFrame([m for m in manifest if m.get("ok")])
    if ok_df.empty:
        _sync()
        raise RuntimeError("All UTCI monthly downloads failed.")
    chosen = (
        ok_df.sort_values(["year", "month", "product_type"])
        .groupby(["year", "month"], as_index=False)
        .first()
    )
    nc_paths: list[Path] = []
    for _, row in chosen.iterrows():
        z = Path(str(row["path"]))
        extracted = extract_zip_to_dir(z, extract_dir)
        if not extracted:
            _sync()
            raise RuntimeError(f"No NetCDF extracted from {z}")
        nc_paths.extend(extracted)
    # unique
    seen = set()
    uniq: list[Path] = []
    for p in nc_paths:
        sp = str(p)
        if sp not in seen:
            seen.add(sp)
            uniq.append(Path(sp))
    nc_paths = uniq
    metadata["cds_downloads_recent"] = {
        "dataset": "derived-utci-historical",
        "n_nc_paths": int(len(nc_paths)),
        "progress_status_path": str(dl_status),
    }

    # Build daily UTCI max stack.
    das = []
    for p in nc_paths:
        ds = xr.open_dataset(p, decode_times=True, engine="netcdf4")
        rename = {}
        if "latitude" in ds.coords and "lat" not in ds.coords:
            rename["latitude"] = "lat"
        if "longitude" in ds.coords and "lon" not in ds.coords:
            rename["longitude"] = "lon"
        if rename:
            ds = ds.rename(rename)
        da = _find_daily_max_utci(ds)
        if "latitude" in da.dims:
            da = da.rename({"latitude": "lat"})
        if "longitude" in da.dims:
            da = da.rename({"longitude": "lon"})
        if "time" not in da.dims or "lat" not in da.dims or "lon" not in da.dims:
            ds.close()
            raise ValueError(f"Unexpected UTCI dims in {p.name}: {da.dims}")
        da = _to_celsius_if_needed(da)
        das.append(da)
        ds.close()
    utci = xr.concat(das, dim="time").sortby("time")
    _, idx = np.unique(utci["time"].values, return_index=True)
    utci = utci.isel(time=np.sort(idx)).sortby("time")
    utci = utci.sel(time=slice(str(config.window_start), str(config.window_end)))
    if int(utci.sizes.get("time", 0)) == 0:
        _sync()
        raise RuntimeError("No UTCI timesteps remain after filtering to requested window.")

    # Build thresholds.
    thresholds = {f"abs_{int(t)}c": float(t) for t in options.abs_thresholds_c}
    default_threshold_key = f"abs_{int(options.default_reporting_threshold_c)}c"
    if default_threshold_key not in thresholds:
        raise ValueError(
            "default_reporting_threshold_c must be present in abs_thresholds_c; "
            f"got {options.default_reporting_threshold_c} and {options.abs_thresholds_c}"
        )
    k = int(options.k_consecutive_days)
    mask_native_dir = layout["rasters"] / "masks_native"
    mask_wp_dir = layout["rasters"] / "masks_worldpop"
    pop_exposed_dir = layout["rasters"] / "pop_exposed"
    for d in (mask_native_dir, mask_wp_dir, pop_exposed_dir):
        d.mkdir(parents=True, exist_ok=True)

    raster_status = layout["logs"] / "utci_raster_compute_status.json"
    raster_writer = make_progress_writer(raster_status, "utci_raster_compute", len(thresholds))
    raster_writer(0, current=None)

    results_summary: dict[str, Any] = {}
    # PERF-005: kept alongside (not inside) results_summary, which is embedded
    # verbatim into metadata and JSON-serialized -- lets the aggregation loop
    # below reuse what was just computed instead of rereading each
    # pop_affected GeoTIFF straight back off disk.
    pop_affected_arrays: dict[str, np.ndarray] = {}
    for i, (thr_name, thr_val) in enumerate(thresholds.items(), start=1):
        exceed = (utci > float(thr_val)).fillna(False)
        consec_mask = _consecutive_k_exceedance(exceed, k=k)
        src_mask = consec_mask.values.astype("uint8")
        src_transform = _transform_from_latlon_centers(consec_mask["lat"].values, consec_mask["lon"].values)
        native_tif = mask_native_dir / f"exceed_{k}day_{thr_name}.tif"
        write_array_geotiff(
            native_tif, src_mask, transform=src_transform, crs="EPSG:4326", nodata=255, dtype="uint8"
        )
        wp_mask = reproject_array_to_grid(
            src_array=src_mask,
            src_transform=src_transform,
            src_crs="EPSG:4326",
            dst_shape=(wp_profile["height"], wp_profile["width"]),
            dst_transform=wp_profile["transform"],
            dst_crs=wp_profile["crs"],
            src_nodata=255,
            dst_nodata=255,
            resampling="nearest",
        ).astype("uint8")
        wp_mask_tif = mask_wp_dir / f"exceed_{k}day_{thr_name}_worldpop.tif"
        write_array_geotiff(
            wp_mask_tif,
            wp_mask,
            transform=wp_profile["transform"],
            crs=wp_profile["crs"],
            nodata=255,
            dtype="uint8",
        )
        pop_exp = np.zeros_like(wp_arr, dtype=np.float32)
        sel = (wp_mask == 1) & pop_valid
        pop_exp[sel] = wp_arr[sel].astype(np.float32)
        pop_tif = pop_exposed_dir / f"pop_affected_{thr_name}.tif"
        write_array_geotiff(
            pop_tif,
            pop_exp,
            transform=wp_profile["transform"],
            crs=wp_profile["crs"],
            nodata=0.0,
            dtype="float32",
        )
        results_summary[thr_name] = {
            "threshold_c": float(thr_val),
            "k_consecutive_days": int(k),
            "mask_native_path": str(native_tif),
            "mask_worldpop_path": str(wp_mask_tif),
            "pop_affected_path": str(pop_tif),
            "pop_affected": float(np.nansum(pop_exp)),
        }
        pop_affected_arrays[thr_name] = pop_exp
        raster_writer(i, current=thr_name)

    # Admin aggregation.
    source_pcode_col = resolve_admin_pcode_column(admin_gdf.columns, adm_level)
    admin_units = admin_gdf[[source_pcode_col, "geometry"]].dropna().copy()
    admin_units_wp = admin_units.to_crs(wp_crs).rename(columns={source_pcode_col: pcode_label})
    shapes = [(geom, idx + 1) for idx, geom in enumerate(admin_units_wp.geometry)]
    admin_id = rasterize(
        shapes=shapes,
        out_shape=wp_shape,
        transform=wp_transform,
        fill=0,
        dtype="int32",
        all_touched=False,
    )
    n_admin = len(admin_units_wp)
    pop_total_by_id = labelled_sum(admin_id, wp_arr, n_labels=n_admin, valid_mask=pop_valid)
    out = pd.DataFrame(
        {
            pcode_label: admin_units_wp[pcode_label].values,
            "admin_id": np.arange(1, n_admin + 1, dtype=int),
        }
    )
    out["pop_total"] = pop_total_by_id
    for thr_name in thresholds.keys():
        arr = pop_affected_arrays[thr_name]
        ok = np.isfinite(arr) & (arr >= 0)
        pop_by_id = labelled_sum(
            admin_id,
            arr,
            n_labels=n_admin,
            valid_mask=pop_valid & ok,
        )
        pcol = f"pop_exposed_{thr_name}"
        ccol = f"pct_exposed_{thr_name}"
        out[pcol] = pop_by_id
        out[ccol] = np.where(out["pop_total"] > 0, (out[pcol] / out["pop_total"]) * 100.0, np.nan)
    out = standardize_admin_summary(
        out,
        config=config,
        admin_level=adm_level,
        admin_pcode_column=pcode_label,
        population_total_column="pop_total",
        population_affected_column=f"pop_exposed_{default_threshold_key}",
        pct_affected_column=f"pct_exposed_{default_threshold_key}",
    )
    vintage = metadata["admin_source"]["vintage"]
    out_csv = layout["tables"] / f"{iso3}_{admin_label}_{vintage}_extreme_heat_{config.as_of_date}.csv"
    out.drop(columns=["admin_id"]).to_csv(out_csv, index=False)
    _append_artifact(metadata, "admin_heat_table", out_csv, f"{admin_label.title()} UTCI exposure table")

    map_paths = write_run_maps(
        admin_gdf,
        out,
        Path(results_summary[default_threshold_key]["mask_worldpop_path"]),
        layout["maps"],
        iso3=iso3,
        pcode_column=pcode_label,
        admin_level=adm_level,
        default_threshold_label=default_threshold_key,
        window_start=config.window_start.isoformat(),
        window_end=config.window_end.isoformat(),
    )
    for kind, path in map_paths.items():
        _append_artifact(metadata, kind, path, f"{admin_label.title()} extreme heat indicator map")

    # Minimal QC JSON for parity.
    qc_json = (
        layout["qc"] / f"{admin_label}_table_qc" / f"qc_{admin_label}_table_{iso3}_{config.as_of_date}.json"
    )
    qc_json.parent.mkdir(parents=True, exist_ok=True)
    qc_payload = {
        f"n_{admin_label}": int(len(out)),
        "admin_level": int(adm_level),
        "admin_pcode_column": pcode_label,
        "country_pop_total_from_table": float(out["pop_total"].sum()),
        "country_pop_total_from_worldpop_raster": float(np.nansum(wp_arr[pop_valid])),
        "raster_checks": {
            kname: {"exists": True, "sum_exposed_pop": float(v["pop_affected"])}
            for kname, v in results_summary.items()
        },
    }
    _write_json(qc_json, qc_payload)
    _append_artifact(metadata, "qc_admin_table_json", qc_json, "UTCI QC summary JSON")

    metadata["pipeline"] = "extreme_heat_utci"
    metadata["aoi"] = {
        "country_bounds_4326": {"west": west, "south": south, "east": east, "north": north},
        "cds_bbox_nwse": cds_bbox,
        "cds_buffer_deg": float(options.cds_buffer_deg),
        "bounds_hash": bounds_hash,
    }
    metadata["extreme_heat_masks"] = {
        "k_consecutive_days": int(k),
        "thresholds_c": thresholds,
        "default_reporting_threshold_key": default_threshold_key,
        "results_summary": results_summary,
        "progress_status_path": str(raster_status),
    }
    metadata["admin_table"] = {
        "path": str(out_csv),
        "admin_layer": options.admin_layer,
        "admin_level": int(adm_level),
        "admin_pcode_column": pcode_label,
        f"n_{admin_label}": int(len(out)),
        "thresholds": thresholds,
        "k_consecutive_days": int(k),
    }
    metadata["qc_report"] = {"path": str(qc_json)}
    # PROD-001: terminal marker so a *future* run can tell this one genuinely
    # finished (vs. the run_metadata.json build_hazard_run_context already
    # wrote at the very start of this run, before any real computation).
    metadata["status"] = "SUCCESS"
    _sync()

    outputs = {
        "admin_table": str(out_csv),
        "qc_json": str(qc_json),
        **{kind: str(path) for kind, path in map_paths.items()},
    }

    return {
        "status": "SUCCESS",
        "run_dir": str(layout["base"]),
        "run_id": config.run_id,
        "metadata_path": str(metadata_path),
        "outputs": outputs,
    }
