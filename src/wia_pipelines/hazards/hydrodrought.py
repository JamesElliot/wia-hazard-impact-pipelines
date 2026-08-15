from __future__ import annotations

import json
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import RunConfig
from ..core.admin import (
    admin_bounds_hash,
    admin_layer_label,
    admin_pcode_label,
    build_admin_aoi,
    filter_admin_for_iso3,
    load_admin_layer,
    resolve_admin_level,
    resolve_admin_pcode_column,
)
from ..core.assets import checksum_path, shared_cache_root
from ..core.cds import months_for_last_n
from ..core.pipeline import (
    build_admin_source,
    build_hazard_run_context,
    standardize_admin_summary,
    sync_run_metadata,
)
from ..core.rivers import clip_reaches_to_aoi, compute_river_corridor, load_river_reaches
from ..core.worldpop import bbox_coverage_report, worldpop_profile_and_bounds
from .coverage_checks import check_worldpop_coverage, evaluate_coverage_gate
from .coverage_requests import days_for_year_month, glofas_sample_request
from .hydrodrought_visualize import write_run_maps

# Decision 4 (monthly SRI-3 rather than raw daily values) means decision 6's
# "duration" rule cannot literally mean 30 consecutive days -- there is no
# sub-month resolution once the series is accumulated monthly. 30 days is
# approximately one month, so the persistence rule is translated to "at
# least PERSISTENCE_MONTHS consecutive months," the natural analogue at this
# cadence. See docs/hydrodrought-implementation-plan.md.
PERSISTENCE_MONTHS = 2


@dataclass(frozen=True)
class HydrodroughtRunInputs:
    iso3: str
    as_of_date: str
    lookback_months: int = 12
    output_root: Path = Path("./outputs")
    target_adm_level: int = 2
    buffer_km: float = 0.0

    def to_run_config(self) -> RunConfig:
        return RunConfig(
            hazard="hydrodrought",
            iso3=self.iso3,
            as_of_date=self.as_of_date,
            lookback_months=self.lookback_months,
            output_root=self.output_root,
            target_adm_level=self.target_adm_level,
            buffer_km=self.buffer_km,
        )


def hydrodrought_month_window(
    as_of_date: str, lookback_months: int = 12, accumulation_months: int = 3
) -> dict[str, Any]:
    """Months to download vs. months actually reported.

    `accumulation_months - 1` extra trailing months are needed before the
    reporting window so the first reported month's rolling accumulation is
    defined (mirrors SPEI's own pre-accumulated CDS product -- now SPEI12,
    computed upstream by CDS there; computed by this pipeline here since
    GloFAS is not pre-accumulated).
    """

    months_for_accumulation = months_for_last_n(
        as_of_date, n_months=lookback_months + accumulation_months - 1
    )
    reported_months = months_for_accumulation[accumulation_months - 1 :]
    return {
        "months_for_accumulation": months_for_accumulation,
        "reported_months": reported_months,
        "accumulation_months": accumulation_months,
        "start_yyyy_mm": f"{reported_months[0][0]:04d}-{reported_months[0][1]:02d}",
        "end_yyyy_mm": f"{reported_months[-1][0]:04d}-{reported_months[-1][1]:02d}",
    }


def build_hydrodrought_run_context(
    inputs: HydrodroughtRunInputs,
    accumulation_months: int = 3,
    create_dirs: bool = True,
    write_metadata: bool = True,
    skip_if_complete: bool = False,
) -> dict[str, Any]:
    config = inputs.to_run_config()
    month_window = hydrodrought_month_window(
        config.as_of_date, config.lookback_months, accumulation_months=accumulation_months
    )
    context = build_hazard_run_context(
        config,
        create_dirs=create_dirs,
        write_metadata=write_metadata,
        metadata_updates={"window_months": [f"{y:04d}-{m:02d}" for y, m in month_window["reported_months"]]},
        skip_if_complete=skip_if_complete,
    )
    context["month_window"] = month_window
    return context


def prepare_hydrodrought_geography(
    iso3: str,
    admin_path: str | Path,
    admin_layer: str = "admin2",
    iso3_field: str = "iso3",
    adm_level_field: str | None = None,
    target_adm_level: int | None = 2,
    buffer_km: float = 0.0,
    worldpop_path: str | Path | None = None,
) -> dict[str, Any]:
    """Same shape as hazards.spei.prepare_spei_geography, one copy per hazard
    module (matches the existing repo convention rather than adding a shared
    abstraction only two callers would use)."""

    admin_all = load_admin_layer(admin_path, layer=admin_layer)
    admin_filtered = filter_admin_for_iso3(
        admin_all,
        iso3=iso3,
        iso3_field=iso3_field,
        adm_level_field=adm_level_field,
        target_adm_level=target_adm_level,
    )
    aoi = build_admin_aoi(admin_filtered, buffer_km=buffer_km, out_crs="EPSG:4326")
    bounds_hash = admin_bounds_hash(iso3=iso3, bounds=aoi["admin_bounds"])

    worldpop = None
    overlap = None
    if worldpop_path is not None:
        worldpop = worldpop_profile_and_bounds(worldpop_path)
        overlap = bbox_coverage_report(aoi["aoi_bounds"], worldpop["bounds_4326"])

    return {
        "admin_gdf": admin_filtered,
        "aoi": aoi,
        "bounds_hash": bounds_hash,
        "worldpop": worldpop,
        "overlap_report": overlap,
    }


@dataclass(frozen=True)
class HydrodroughtPipelineRunOptions:
    inputs: HydrodroughtRunInputs
    admin_path: Path
    worldpop_path: Path
    hydrorivers_path: Path
    admin_layer: str = "admin2"
    iso3_field: str = "iso3"
    cds_buffer_deg: float = 0.25
    accumulation_months: int = 3
    baseline_start_year: int = 1991
    baseline_end_year: int = 2020
    corridor_base_width_km: float = 5.0
    corridor_per_order_km: float = 0.0
    thresholds: dict[str, float] | None = None
    default_threshold_key: str = f"rel_sri_le_m1p5_p{PERSISTENCE_MONTHS}m"
    require_full_preflight_coverage: bool = True
    preflight_coverage_hard_min_pct: float = 50.0
    ewds_url: str | None = None
    ewds_key: str | None = None
    skip_if_complete: bool = False


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _resolve_thresholds(thresholds: dict[str, float] | None) -> dict[str, float]:
    if thresholds:
        return {str(k): float(v) for k, v in thresholds.items()}
    return {
        "rel_sri_le_m1p0": -1.0,
        "rel_sri_le_m1p5": -1.5,
        "rel_sri_le_m2p0": -2.0,
    }


def _find_discharge_var(ds) -> str:
    preferred = ("dis24", "dis", "discharge", "river_discharge")
    spatial_pairs = (("lat", "lon"), ("latitude", "longitude"), ("y", "x"))
    # cems-glofas-historical names its time dimension "valid_time", not
    # "time" (confirmed against the live EWDS response), unlike SPEI/UTCI's
    # CDS products.
    time_dim_names = ("time", "valid_time")

    def _is_spatial_time_var(name: str) -> bool:
        dims = set(ds[name].dims)
        return any(t in dims for t in time_dim_names) and any(
            set(pair).issubset(dims) for pair in spatial_pairs
        )

    candidates = [v for v in ds.data_vars if v.lower() != "crs"]
    if not candidates:
        raise KeyError(f"No discharge variable found in dataset variables {list(ds.data_vars)}")
    for v in preferred:
        if v in candidates and _is_spatial_time_var(v):
            return v
    for v in candidates:
        if _is_spatial_time_var(v):
            return v
    dim_map = {v: tuple(ds[v].dims) for v in candidates}
    raise KeyError(
        f"No discharge variable with required dims (time + spatial pair) found. Candidate dims: {dim_map}"
    )


def _extract_or_use_directly(downloaded_path: Path, extract_dir: Path) -> list[Path]:
    """EWDS's `cems-glofas-historical` does not always wrap its result in a
    zip the way this repo's SPEI/UTCI CDS downloads do -- a single-variable,
    single-day request comes back as a raw NetCDF file even though nothing in
    the request asked for that (confirmed empirically against the live
    EWDS API; see docs/hydrodrought-implementation-plan.md s7). Handle both
    so a future response shape change on either side doesn't silently break
    this."""

    import zipfile

    from ..core.cds import extract_zip_to_dir

    if zipfile.is_zipfile(downloaded_path):
        return extract_zip_to_dir(downloaded_path, extract_dir)
    return [downloaded_path]


def _ensure_rio_spatial_dims(da):
    dims = set(da.dims)
    if {"lat", "lon"}.issubset(dims):
        return da.rio.set_spatial_dims(x_dim="lon", y_dim="lat", inplace=False)
    if {"latitude", "longitude"}.issubset(dims):
        da2 = da.rename({"latitude": "lat", "longitude": "lon"})
        return da2.rio.set_spatial_dims(x_dim="lon", y_dim="lat", inplace=False)
    if {"x", "y"}.issubset(dims):
        return da.rio.set_spatial_dims(x_dim="x", y_dim="y", inplace=False)
    raise ValueError(f"Could not infer spatial dims for DataArray with dims={da.dims}.")


def _download_monthly_mean_discharge(
    months: list[tuple[int, int]],
    *,
    iso3: str,
    cache_key: str,
    cds_area: list[float],
    cache_dirs: dict[str, Path],
    logs_dir: Path,
    ewds_url: str | None,
    ewds_key: str | None,
    status_label: str,
):
    """One EWDS request per (year, month) -- mirrors the SPEI/UTCI per-month
    download loop already used in this repo -- immediately reduced to a
    single monthly-mean 2D grid so daily stacks never accumulate in memory
    across (potentially many) baseline months."""

    import numpy as np
    import xarray as xr

    from ..core.ewds import download_ewds
    from ..core.io_paths import append_artifact  # noqa: F401 (kept for parity with other loops)

    started = time.perf_counter()
    status_path = logs_dir / f"{iso3}_hydrodrought_{status_label}_download_status.json"

    def _status(processed: int, total: int, current: str | None) -> None:
        elapsed = max(0.0, time.perf_counter() - started)
        rate = (processed / elapsed) if elapsed > 0 else 0.0
        remaining = max(0, total - processed)
        eta = (remaining / rate) if rate > 0 else None
        _write_json(
            status_path,
            {
                "stage": status_label,
                "processed": int(processed),
                "total": int(total),
                "pct_complete": float((processed / total) * 100.0) if total else 100.0,
                "elapsed_seconds": float(round(elapsed, 2)),
                "eta_seconds": None if eta is None else float(round(eta, 2)),
                "current": current,
            },
        )

    monthly_das = []
    manifest: list[dict[str, Any]] = []
    _status(0, len(months), None)
    for idx, (y, m) in enumerate(months, start=1):
        month_label = f"{y}-{m:02d}"
        raw_path = cache_dirs["glofas_raw"] / f"{cache_key}_{y}{m:02d}.download"
        ok = raw_path.exists() and raw_path.stat().st_size > 0
        err = None
        if not ok:
            request = {
                "system_version": ["version_4_0"],
                "hydrological_model": ["lisflood"],
                "product_type": ["consolidated"],
                "timespan": ["time_mean"],
                "variable": ["average_river_discharge_in_the_last_24_hours"],
                "year": [str(y)],
                "month": [f"{m:02d}"],
                "day": days_for_year_month(y, m),
                "data_format": "netcdf",
                "download_format": "unarchived",
                "area": cds_area,
            }
            ok, err = download_ewds("cems-glofas-historical", request, raw_path, url=ewds_url, key=ewds_key)
        manifest.append({"year": y, "month": f"{m:02d}", "ok": bool(ok), "error": err, "path": str(raw_path)})
        if not ok:
            _status(idx, len(months), month_label)
            continue

        extracted = _extract_or_use_directly(raw_path, cache_dirs["glofas_extracted"])
        if not extracted:
            manifest[-1]["error"] = "no_nc_extracted"
            _status(idx, len(months), month_label)
            continue

        ds = xr.open_dataset(extracted[0], decode_times=True, engine="netcdf4")
        try:
            da = ds[_find_discharge_var(ds)]
            rename = {}
            if "valid_time" in da.dims:
                rename["valid_time"] = "time"
            if "latitude" in da.dims:
                rename["latitude"] = "lat"
            if "longitude" in da.dims:
                rename["longitude"] = "lon"
            if rename:
                da = da.rename(rename)
            monthly_mean = da.mean(dim="time", skipna=True)
            monthly_mean = monthly_mean.expand_dims(time=[np.datetime64(f"{y:04d}-{m:02d}-01")])
            monthly_das.append(monthly_mean.load())
        finally:
            ds.close()
        _status(idx, len(months), month_label)

    manifest_path = logs_dir / f"{iso3}_hydrodrought_{status_label}_manifest.csv"
    import pandas as pd

    pd.DataFrame(manifest).to_csv(manifest_path, index=False)

    ok_count = sum(1 for row in manifest if row.get("ok"))
    if ok_count == 0:
        first_error = next((row.get("error") for row in manifest if row.get("error")), "Unknown")
        raise RuntimeError(f"All GloFAS downloads failed for '{status_label}'. Example error: {first_error}")
    if not monthly_das:
        raise RuntimeError(f"No monthly discharge grids assembled for '{status_label}'.")

    stacked = xr.concat(monthly_das, dim="time").sortby("time")
    return stacked, manifest_path


def _mask_da_transform(mask_da_2d):
    from rasterio.transform import from_origin

    lats = mask_da_2d["lat"].values
    lons = mask_da_2d["lon"].values
    dlat = float(abs(lats[1] - lats[0]))
    dlon = float(abs(lons[1] - lons[0]))
    north0 = float(max(lats) + dlat / 2.0)
    west0 = float(min(lons) - dlon / 2.0)
    return from_origin(west0, north0, dlon, dlat)


def _persistent_occurrence(below: Any, min_consecutive: int) -> Any:
    """`below` is a boolean array with time as axis 0. True where a run of
    at least `min_consecutive` consecutive True values occurs somewhere along
    axis 0."""

    import numpy as np

    if min_consecutive <= 1:
        return np.any(below, axis=0)
    n_time = below.shape[0]
    if n_time < min_consecutive:
        return np.zeros(below.shape[1:], dtype=bool)
    result = np.zeros(below.shape[1:], dtype=bool)
    # A run is persistent at position `start` if below[start:start+k] are all True.
    for start in range(0, n_time - min_consecutive + 1):
        result |= np.all(below[start : start + min_consecutive], axis=0)
    return result


def run_hydrodrought_pipeline(options: HydrodroughtPipelineRunOptions) -> dict[str, Any]:
    import numpy as np
    import pandas as pd
    import rasterio
    import rioxarray  # noqa: F401
    from rasterio.features import rasterize
    from shapely.geometry import mapping
    from shapely.ops import unary_union

    from ..core.aggregation import labelled_sum
    from ..core.io_paths import append_artifact
    from ..core.raster_ops import write_array_geotiff
    from ..core.standardize import fit_baseline_distribution, standardize_values

    inputs = options.inputs
    iso3 = inputs.iso3.upper()
    if not options.admin_path.exists():
        raise FileNotFoundError(f"Admin boundaries not found: {options.admin_path}")
    if not options.worldpop_path.exists():
        raise FileNotFoundError(f"WorldPop raster not found: {options.worldpop_path}")
    if not options.hydrorivers_path.exists():
        raise FileNotFoundError(f"HydroRIVERS dataset not found: {options.hydrorivers_path}")

    thresholds = _resolve_thresholds(options.thresholds)
    default_base_key = options.default_threshold_key.split("_p")[0]
    if default_base_key not in thresholds:
        raise ValueError(
            f"default_threshold_key '{options.default_threshold_key}' must be one of the threshold keys "
            f"{sorted(thresholds)}, optionally suffixed with '_p{PERSISTENCE_MONTHS}m' for the persistence variant."
        )

    ctx = build_hydrodrought_run_context(
        inputs=inputs,
        accumulation_months=options.accumulation_months,
        create_dirs=True,
        write_metadata=True,
        skip_if_complete=options.skip_if_complete,
    )
    config = ctx["config"]
    layout = ctx["layout"]
    metadata = ctx["metadata"]
    metadata_path = ctx["metadata_path"]
    month_window = ctx["month_window"]

    def _sync_metadata() -> None:
        sync_run_metadata(metadata, metadata_path)

    dirs = {
        "raw_glofas": layout["raw"] / "glofas",
        "masks_native": layout["rasters"] / "masks_native" / "hydrodrought",
        "masks_worldpop": layout["rasters"] / "masks_worldpop" / "hydrodrought",
        "pop_affected": layout["rasters"] / "pop_affected" / "hydrodrought",
        "qc": layout["qc"] / "hydrodrought",
        "logs": layout["logs"],
    }
    for p in dirs.values():
        p.mkdir(parents=True, exist_ok=True)

    cache_root = Path(config.output_root).resolve() / "_cache" / "hydro_drought_glofas_sri" / iso3
    cache_dirs = {
        "glofas_raw": cache_root / "glofas_raw",
        "glofas_extracted": cache_root / "glofas_raw" / "extracted",
    }
    for p in cache_dirs.values():
        p.mkdir(parents=True, exist_ok=True)

    geo = prepare_hydrodrought_geography(
        iso3=iso3,
        admin_path=options.admin_path,
        admin_layer=options.admin_layer,
        iso3_field=options.iso3_field,
        target_adm_level=config.target_adm_level,
        worldpop_path=options.worldpop_path,
    )
    adm_level = resolve_admin_level(options.admin_layer, config.target_adm_level)
    admin_label = admin_layer_label(adm_level)
    pcode_label = admin_pcode_label(adm_level)

    admin_gdf = geo["admin_gdf"].copy()
    admin_4326 = admin_gdf.to_crs("EPSG:4326").copy()
    country_geom_4326 = unary_union(admin_4326.geometry)
    west, south, east, north = tuple(float(v) for v in country_geom_4326.bounds)
    west_cds = max(-180.0, west - float(options.cds_buffer_deg))
    south_cds = max(-90.0, south - float(options.cds_buffer_deg))
    east_cds = min(180.0, east + float(options.cds_buffer_deg))
    north_cds = min(90.0, north + float(options.cds_buffer_deg))
    cds_area = [north_cds, west_cds, south_cds, east_cds]

    aoi_hash = admin_bounds_hash(iso3=iso3, bounds=(west_cds, south_cds, east_cds, north_cds))

    # River reaches: bbox-prefiltered at read time (HydroRIVERS is a single
    # global layer of ~8.5 million reaches; loading it unfiltered before
    # clipping is impractically slow), then clipped to the exact AOI geometry.
    reaches_bbox = load_river_reaches(
        options.hydrorivers_path, bbox=(west_cds, south_cds, east_cds, north_cds)
    )
    reaches = clip_reaches_to_aoi(reaches_bbox, country_geom_4326, out_crs="EPSG:4326")

    # WorldPop base raster.
    with rasterio.open(options.worldpop_path) as wp:
        # PERF-007: float32, not float64 -- halves this array's memory footprint
        # (and several same-shape arrays derived from it) at country scale.
        # Summation still upcasts explicitly at the reduction step below, so
        # this doesn't trade away precision on the totals that matter.
        wp_arr = wp.read(1).astype("float32")
        wp_profile = wp.profile.copy()
        wp_transform = wp.transform
        wp_crs = wp.crs
        wp_shape = (wp.height, wp.width)
        wp_nodata = wp.nodata
    wp_profile.update(count=1)
    pop_valid_mask = np.isfinite(wp_arr)
    if wp_nodata is not None:
        pop_valid_mask &= wp_arr != float(wp_nodata)
    pop_valid_mask &= wp_arr >= 0
    worldpop_total = float(np.nansum(wp_arr[pop_valid_mask], dtype="float64"))
    append_artifact(
        metadata, "worldpop_raster", options.worldpop_path, "Country WorldPop raster used as aggregation grid"
    )
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

    # Preflight: WorldPop bbox coverage + a single-day GloFAS sample.
    reported_months = month_window["reported_months"]
    sample_year, sample_month = reported_months[0]
    wp_cov = check_worldpop_coverage((west, south, east, north), options.worldpop_path)
    sample_path = (
        dirs["logs"] / "preflight" / f"{iso3}_hydrodrought_sample_{sample_year}{sample_month:02d}.download"
    )
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    sample_req = glofas_sample_request(sample_year, sample_month, 1, cds_area)
    from ..core.ewds import download_ewds

    if sample_path.exists() and sample_path.stat().st_size > 0:
        sample_ok, sample_err = True, None
    else:
        sample_ok, sample_err = download_ewds(
            "cems-glofas-historical", sample_req, sample_path, url=options.ewds_url, key=options.ewds_key
        )
    metadata["preflight_coverage"] = {
        "sample_year": sample_year,
        "sample_month": sample_month,
        "worldpop": wp_cov,
        "glofas_sample": {"ok": sample_ok, "error": sample_err},
    }
    if not sample_ok:
        _sync_metadata()
        raise RuntimeError(
            f"GloFAS/EWDS preflight sample failed: {sample_err}. See "
            "docs/hydrodrought-implementation-plan.md s7 for EWDS credential setup."
        )
    if options.require_full_preflight_coverage:
        wp_gate = evaluate_coverage_gate(
            wp_cov.get("coverage_pct", 0.0),
            target_pct=100.0,
            hard_min_pct=options.preflight_coverage_hard_min_pct,
        )
        if wp_gate == "warn":
            warn_msg = (
                "WorldPop preflight coverage below target (100%); continuing because it meets the hard minimum. "
                f"Observed={wp_cov.get('coverage_pct'):.3f}% HardMin={options.preflight_coverage_hard_min_pct:.3f}%"
            )
            warnings.warn(warn_msg, RuntimeWarning, stacklevel=2)
            metadata.setdefault("warnings", [])
            metadata["warnings"].append({"stage": "preflight_coverage", "message": warn_msg})
        elif wp_gate == "fail":
            _sync_metadata()
            raise RuntimeError(
                f"WorldPop preflight coverage is not full ({wp_cov.get('coverage_pct'):.3f}%)."
            )

    # Baseline + analysis-window monthly-mean discharge.
    baseline_years = list(range(int(options.baseline_start_year), int(options.baseline_end_year) + 1))
    baseline_months = [(y, m) for y in baseline_years for m in range(1, 13)]
    end_yyyymm = pd.to_datetime(config.as_of_date).strftime("%Y%m")
    cache_key = f"{iso3}_glofas_{aoi_hash}_{end_yyyymm}"

    baseline_da, baseline_manifest = _download_monthly_mean_discharge(
        baseline_months,
        iso3=iso3,
        cache_key=f"{cache_key}_baseline",
        cds_area=cds_area,
        cache_dirs=cache_dirs,
        logs_dir=dirs["logs"],
        ewds_url=options.ewds_url,
        ewds_key=options.ewds_key,
        status_label="baseline",
    )
    window_da, window_manifest = _download_monthly_mean_discharge(
        month_window["months_for_accumulation"],
        iso3=iso3,
        cache_key=f"{cache_key}_window",
        cds_area=cds_area,
        cache_dirs=cache_dirs,
        logs_dir=dirs["logs"],
        ewds_url=options.ewds_url,
        ewds_key=options.ewds_key,
        status_label="window",
    )
    append_artifact(
        metadata, "glofas_baseline_manifest", baseline_manifest, f"{len(baseline_months)} baseline months"
    )
    append_artifact(
        metadata,
        "glofas_window_manifest",
        window_manifest,
        f"{len(month_window['months_for_accumulation'])} window months",
    )

    baseline_da = _ensure_rio_spatial_dims(baseline_da).rio.write_crs("EPSG:4326", inplace=False)
    window_da = _ensure_rio_spatial_dims(window_da).rio.write_crs("EPSG:4326", inplace=False)
    baseline_da = baseline_da.rio.clip(
        [mapping(country_geom_4326)], crs="EPSG:4326", drop=True, all_touched=True
    )
    window_da = window_da.rio.clip([mapping(country_geom_4326)], crs="EPSG:4326", drop=True, all_touched=True)
    baseline_da = _ensure_rio_spatial_dims(baseline_da)
    window_da = _ensure_rio_spatial_dims(window_da)

    accumulation_months = int(options.accumulation_months)
    baseline_accum = baseline_da.rolling(time=accumulation_months, min_periods=accumulation_months).sum()
    window_accum = window_da.rolling(time=accumulation_months, min_periods=accumulation_months).sum()
    window_accum = window_accum.isel(time=slice(accumulation_months - 1, None))
    if int(window_accum.sizes.get("time", 0)) != len(reported_months):
        raise RuntimeError(
            "Accumulated window series length does not match the requested reported months "
            f"({int(window_accum.sizes.get('time', 0))} != {len(reported_months)})."
        )

    baseline_values = baseline_accum.values  # (time, lat, lon)
    window_values = window_accum.values  # (time, lat, lon)
    lat_size, lon_size = baseline_values.shape[1], baseline_values.shape[2]

    sri_window = np.full(window_values.shape, np.nan, dtype="float64")
    n_gamma_cells = 0
    n_empirical_cells = 0
    for i in range(lat_size):
        for j in range(lon_size):
            base_col = baseline_values[:, i, j]
            base_col = base_col[np.isfinite(base_col)]
            if base_col.size < 5:
                continue
            dist = fit_baseline_distribution(base_col)
            if dist.method == "gamma":
                n_gamma_cells += 1
            else:
                n_empirical_cells += 1
            sri_window[:, i, j] = standardize_values(window_values[:, i, j], dist)

    sri_da = window_accum.copy(data=sri_window)

    products: dict[str, Any] = {}
    native_masks: dict[str, Any] = {}
    for key, thr in thresholds.items():
        below = np.where(np.isfinite(sri_window), sri_window <= float(thr), False)
        any_mask = np.any(below, axis=0)
        persistent_mask = _persistent_occurrence(below, PERSISTENCE_MONTHS)

        for variant_key, variant_mask in (
            (key, any_mask),
            (f"{key}_p{PERSISTENCE_MONTHS}m", persistent_mask),
        ):
            native_masks[variant_key] = variant_mask
            src_transform = _mask_da_transform(sri_da.isel(time=0))
            native_path = dirs["masks_native"] / f"hydrodrought_mask_{variant_key}_native.tif"
            write_array_geotiff(
                native_path,
                variant_mask.astype(np.uint8),
                transform=src_transform,
                crs="EPSG:4326",
                nodata=255,
                dtype="uint8",
            )
            products[variant_key] = {
                "threshold": float(thr),
                "persistence_months": PERSISTENCE_MONTHS if variant_key.endswith("m") else 1,
                "mask_native_path": str(native_path),
            }

    # River corridor: nearest-reach assignment on the WorldPop grid.
    corridor = compute_river_corridor(
        reaches,
        wp_shape,
        wp_transform,
        base_width_km=options.corridor_base_width_km,
        per_order_km=options.corridor_per_order_km,
    )
    nearest_reach_index = corridor["nearest_reach_index"]
    corridor_mask = corridor["mask"]

    # Sample each variant's coarse native mask at every reach's representative
    # point, giving each reach a severity flag; then broadcast that flag onto
    # the WorldPop grid via the corridor's nearest-reach assignment.
    src_transform = _mask_da_transform(sri_da.isel(time=0))
    inv_transform = ~src_transform
    reach_points = reaches.geometry.centroid
    reach_cols_rows = [inv_transform * (float(pt.x), float(pt.y)) for pt in reach_points]
    reach_rows = np.clip(np.array([int(rc[1]) for rc in reach_cols_rows]), 0, lat_size - 1)
    reach_cols = np.clip(np.array([int(rc[0]) for rc in reach_cols_rows]), 0, lon_size - 1)

    # PERF-005: kept alongside (not inside) `products`, which is embedded
    # verbatim into metadata and JSON-serialized -- lets the aggregation loop
    # below reuse what was just computed instead of rereading each
    # pop_affected GeoTIFF straight back off disk.
    pop_affected_arrays: dict[str, np.ndarray] = {}
    for variant_key in list(products.keys()):
        native_mask = native_masks[variant_key]
        reach_severity = native_mask[reach_rows, reach_cols] if len(reaches) else np.zeros(0, dtype=bool)

        has_reach = nearest_reach_index >= 0
        safe_idx = np.clip(nearest_reach_index, 0, max(len(reaches) - 1, 0))
        pixel_severity = reach_severity[safe_idx] if len(reaches) else np.zeros(wp_shape, dtype=bool)
        mask_wp = (corridor_mask & has_reach & pixel_severity).astype(np.uint8)

        mask_wp_path = dirs["masks_worldpop"] / f"hydrodrought_mask_{variant_key}_worldpop.tif"
        write_array_geotiff(
            mask_wp_path,
            mask_wp,
            transform=wp_profile["transform"],
            crs=wp_profile["crs"],
            nodata=255,
            dtype="uint8",
        )
        pop_affected = np.zeros_like(wp_arr, dtype=np.float32)
        affected = (mask_wp == 1) & pop_valid_mask
        pop_affected[affected] = wp_arr[affected].astype(np.float32)
        pop_path = dirs["pop_affected"] / f"hydrodrought_pop_affected_{variant_key}.tif"
        write_array_geotiff(
            pop_path,
            pop_affected,
            transform=wp_profile["transform"],
            crs=wp_profile["crs"],
            nodata=0.0,
            dtype="float32",
        )
        products[variant_key]["mask_worldpop_path"] = str(mask_wp_path)
        products[variant_key]["pop_affected_path"] = str(pop_path)
        products[variant_key]["pop_affected_sum"] = float(np.nansum(pop_affected))
        pop_affected_arrays[variant_key] = pop_affected

    # Admin aggregation.
    admin_units = admin_gdf.copy()
    source_pcode_col = resolve_admin_pcode_column(admin_units.columns, adm_level)
    admin_units = (
        admin_units[[source_pcode_col, "geometry"]]
        .dropna(subset=[source_pcode_col, "geometry"])
        .reset_index(drop=True)
    )
    admin_units_wp = admin_units.to_crs(wp_crs).rename(columns={source_pcode_col: pcode_label})
    shapes = [(geom, i + 1) for i, geom in enumerate(admin_units_wp.geometry)]
    admin_id_raster = rasterize(
        shapes=shapes, out_shape=wp_shape, transform=wp_transform, fill=0, dtype="int32", all_touched=False
    )
    n_admin = len(admin_units_wp)
    pop_total_by_id = labelled_sum(admin_id_raster, wp_arr, n_labels=n_admin, valid_mask=pop_valid_mask)
    out = pd.DataFrame(
        {pcode_label: admin_units_wp[pcode_label].values, "admin_id": np.arange(1, n_admin + 1, dtype=int)}
    )
    out["pop_total"] = pop_total_by_id

    for variant_key in products:
        arr = pop_affected_arrays[variant_key]
        arr_ok = np.isfinite(arr) & (arr >= 0)
        pop_aff_by_id = labelled_sum(
            admin_id_raster, arr, n_labels=n_admin, valid_mask=pop_valid_mask & arr_ok
        )
        col_pop = f"pop_affected_{variant_key}"
        col_pct = f"pct_affected_{variant_key}"
        out[col_pop] = pop_aff_by_id
        out[col_pct] = np.where(out["pop_total"] > 0, (out[col_pop] / out["pop_total"]) * 100.0, np.nan)

    default_key = options.default_threshold_key
    if f"pop_affected_{default_key}" not in out.columns:
        raise KeyError(f"default_threshold_key '{default_key}' did not produce a staged column.")

    out = standardize_admin_summary(
        out,
        config=config,
        admin_level=adm_level,
        admin_pcode_column=pcode_label,
        population_total_column="pop_total",
        population_affected_column=f"pop_affected_{default_key}",
        pct_affected_column=f"pct_affected_{default_key}",
    )
    vintage = metadata["admin_source"]["vintage"]
    out_csv = layout["tables"] / f"{iso3}_{admin_label}_{vintage}_hydro_drought_glofas_sri_{config.as_of_date}.csv"
    out.drop(columns=["admin_id"]).to_csv(out_csv, index=False)
    append_artifact(
        metadata, "admin_hydrodrought_table", out_csv, f"{admin_label.title()} GloFAS SRI exposure table"
    )

    map_paths = write_run_maps(
        admin_gdf,
        out,
        Path(products[default_key]["mask_worldpop_path"]),
        layout["maps"],
        iso3=iso3,
        pcode_column=pcode_label,
        admin_level=adm_level,
        default_threshold_label=default_key,
        window_start=config.window_start.isoformat(),
        window_end=config.window_end.isoformat(),
    )
    for kind, path in map_paths.items():
        append_artifact(metadata, kind, path, f"{admin_label.title()} hydrological drought indicator map")

    qc_csv = dirs["qc"] / f"{iso3}_hydrodrought_qc_{config.as_of_date}.csv"
    mask_pop_sum = float(out[f"pop_affected_{default_key}"].sum())
    qc_df = pd.DataFrame(
        [
            {
                "iso3": iso3,
                "as_of_date": config.as_of_date,
                "window_months": ", ".join(f"{y:04d}-{m:02d}" for y, m in reported_months),
                "accumulation_months": accumulation_months,
                "baseline_start_year": options.baseline_start_year,
                "baseline_end_year": options.baseline_end_year,
                "default_threshold_key": default_key,
                "default_threshold_value": float(thresholds.get(default_key.split("_p")[0], float("nan"))),
                "n_river_reaches": int(len(reaches)),
                "corridor_base_width_km": options.corridor_base_width_km,
                "n_gamma_cells": n_gamma_cells,
                "n_empirical_cells": n_empirical_cells,
                "worldpop_total_pop": worldpop_total,
                "mask_pop_sum": mask_pop_sum,
                "pop_affected_sum": float(products[default_key]["pop_affected_sum"]),
            }
        ]
    )
    qc_df.to_csv(qc_csv, index=False)
    append_artifact(metadata, "hydrodrought_qc_table", qc_csv, "Hydrological drought QC summary table")

    metadata["pipeline"] = "hydro_drought_glofas_sri"
    metadata["aoi"] = {
        "country_bounds_4326": {"west": west, "south": south, "east": east, "north": north},
        "cds_area": cds_area,
        "cds_buffer_deg": float(options.cds_buffer_deg),
        "bounds_hash": aoi_hash,
    }
    metadata["worldpop"] = {
        "path": str(options.worldpop_path),
        "crs": str(wp_crs),
        "shape": [int(wp_shape[0]), int(wp_shape[1])],
        "total_pop_valid": worldpop_total,
    }
    metadata["river_corridor"] = {
        "hydrorivers_path": str(options.hydrorivers_path),
        "n_reaches": int(len(reaches)),
        "base_width_km": float(options.corridor_base_width_km),
        "per_order_km": float(options.corridor_per_order_km),
    }
    metadata["hydrodrought_baseline"] = {
        "start_year": int(options.baseline_start_year),
        "end_year": int(options.baseline_end_year),
        "n_months": int(len(baseline_months)),
        "n_gamma_cells": n_gamma_cells,
        "n_empirical_cells": n_empirical_cells,
    }
    metadata["hydrodrought_masks"] = {
        "thresholds": {k: float(v) for k, v in thresholds.items()},
        "default_key": default_key,
        "persistence_months": PERSISTENCE_MONTHS,
        "accumulation_months": accumulation_months,
        "products": {k: {kk: vv for kk, vv in v.items()} for k, v in products.items()},
        "window_months": [f"{y:04d}-{m:02d}" for y, m in reported_months],
        "aggregation_rule": (
            f"any_month_sri_le_threshold OR >= {PERSISTENCE_MONTHS}_consecutive_months_sri_le_threshold"
        ),
    }
    metadata["hydrodrought_qc"] = {"qc_csv": str(qc_csv)}
    # PROD-001: terminal marker so a *future* run can tell this one genuinely
    # finished (vs. the run_metadata.json build_hazard_run_context already
    # wrote at the very start of this run, before any real computation).
    metadata["status"] = "SUCCESS"
    _sync_metadata()

    outputs = {
        "admin_table": str(out_csv),
        "qc_csv": str(qc_csv),
        "default_pop_affected_tif": products[default_key]["pop_affected_path"],
        **{kind: str(path) for kind, path in map_paths.items()},
    }
    return {
        "status": "SUCCESS",
        "run_dir": str(layout["base"]),
        "run_id": config.run_id,
        "metadata_path": str(metadata_path),
        "outputs": outputs,
    }
