from __future__ import annotations

import json
import time
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
from ..core.cds import months_for_last_n
from ..core.pipeline import build_hazard_run_context, standardize_admin_summary, sync_run_metadata
from ..core.worldpop import bbox_coverage_report, worldpop_profile_and_bounds
from .coverage_checks import (
    check_worldpop_coverage,
    run_cds_single_month_check,
    spei_sample_request,
)


@dataclass(frozen=True)
class SpeiRunInputs:
    iso3: str
    as_of_date: str
    lookback_months: int = 12
    output_root: Path = Path("./outputs")
    target_adm_level: int = 2
    buffer_km: float = 0.0

    def to_run_config(self) -> RunConfig:
        return RunConfig(
            hazard="drought",
            iso3=self.iso3,
            as_of_date=self.as_of_date,
            lookback_months=self.lookback_months,
            output_root=self.output_root,
            target_adm_level=self.target_adm_level,
            buffer_km=self.buffer_km,
        )


def spei_month_window(as_of_date: str, lookback_months: int = 12) -> dict[str, Any]:
    months = months_for_last_n(as_of_date, n_months=lookback_months)
    return {
        "months": months,
        "start_yyyy_mm": f"{months[0][0]:04d}-{months[0][1]:02d}",
        "end_yyyy_mm": f"{months[-1][0]:04d}-{months[-1][1]:02d}",
    }


def build_spei_run_context(
    inputs: SpeiRunInputs,
    create_dirs: bool = True,
    write_metadata: bool = True,
) -> dict[str, Any]:
    config = inputs.to_run_config()
    month_window = spei_month_window(config.as_of_date, config.lookback_months)
    context = build_hazard_run_context(
        config,
        create_dirs=create_dirs,
        write_metadata=write_metadata,
        metadata_updates={"window_months": [f"{y:04d}-{m:02d}" for y, m in month_window["months"]]},
    )
    context["month_window"] = month_window
    return context


def prepare_spei_geography(
    iso3: str,
    admin_path: str | Path,
    admin_layer: str = "admin2",
    iso3_field: str = "iso3",
    adm_level_field: str | None = None,
    target_adm_level: int | None = 2,
    buffer_km: float = 0.0,
    worldpop_path: str | Path | None = None,
) -> dict[str, Any]:
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
class SpeiPipelineRunOptions:
    inputs: SpeiRunInputs
    admin_path: Path
    worldpop_path: Path
    admin_layer: str = "admin2"
    iso3_field: str = "iso3"
    cds_buffer_deg: float = 0.25
    thresholds: dict[str, float] | None = None
    default_threshold_key: str = "rel_spei_le_m1p5"
    require_full_preflight_coverage: bool = True


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_status(path: Path, payload: dict[str, Any]) -> None:
    _write_json(path, payload)


def _resolve_thresholds(thresholds: dict[str, float] | None) -> dict[str, float]:
    if thresholds:
        return {str(k): float(v) for k, v in thresholds.items()}
    return {
        "rel_spei_le_m1p0": -1.0,
        "rel_spei_le_m1p5": -1.5,
        "rel_spei_le_m2p0": -2.0,
    }


def _find_spei_var(ds) -> str:
    preferred = ("SPEI3", "spei3", "spei", "standardised_precipitation_evapotranspiration_index")
    spatial_pairs = (("lat", "lon"), ("latitude", "longitude"), ("y", "x"))

    def _is_spatial_time_var(name: str) -> bool:
        da = ds[name]
        dims = set(da.dims)
        return ("time" in dims) and any(set(pair).issubset(dims) for pair in spatial_pairs)

    candidates = [v for v in ds.data_vars if v.lower() != "crs"]
    if not candidates:
        raise KeyError(f"No SPEI variable found in dataset variables {list(ds.data_vars)}")

    for v in preferred:
        if v in candidates and _is_spatial_time_var(v):
            return v

    for v in candidates:
        if _is_spatial_time_var(v):
            return v

    dim_map = {v: tuple(ds[v].dims) for v in candidates}
    raise KeyError(
        f"No SPEI variable with required dims (time + spatial pair) found. Candidate dims: {dim_map}"
    )


def _ensure_rio_spatial_dims(da):
    """
    Ensure rioxarray knows which dims are spatial after xarray transforms.
    Some concat/slice ops can drop this mapping metadata.
    """
    dims = set(da.dims)
    if {"lat", "lon"}.issubset(dims):
        return da.rio.set_spatial_dims(x_dim="lon", y_dim="lat", inplace=False)
    if {"latitude", "longitude"}.issubset(dims):
        da2 = da.rename({"latitude": "lat", "longitude": "lon"})
        return da2.rio.set_spatial_dims(x_dim="lon", y_dim="lat", inplace=False)
    if {"x", "y"}.issubset(dims):
        return da.rio.set_spatial_dims(x_dim="x", y_dim="y", inplace=False)
    raise ValueError(f"Could not infer spatial dims for DataArray with dims={da.dims}.")


def run_spei_pipeline(options: SpeiPipelineRunOptions) -> dict[str, Any]:
    import numpy as np
    import pandas as pd
    import rasterio
    import rioxarray  # noqa: F401
    import xarray as xr
    from rasterio.features import rasterize
    from rasterio.transform import from_origin
    from shapely.geometry import mapping
    from shapely.ops import unary_union

    from ..core.cds import download_cds, ensure_downloads, extract_zip_to_dir, months_for_last_n
    from ..core.aggregation import labelled_sum
    from ..core.io_paths import append_artifact
    from ..core.raster_ops import reproject_array_to_grid, write_array_geotiff

    inputs = options.inputs
    iso3 = inputs.iso3.upper()
    if not options.admin_path.exists():
        raise FileNotFoundError(f"Admin boundaries not found: {options.admin_path}")
    if not options.worldpop_path.exists():
        raise FileNotFoundError(f"WorldPop raster not found: {options.worldpop_path}")

    thresholds = _resolve_thresholds(options.thresholds)
    if options.default_threshold_key not in thresholds:
        raise ValueError(
            f"default_threshold_key '{options.default_threshold_key}' not in thresholds keys {sorted(thresholds)}"
        )

    ctx = build_spei_run_context(inputs=inputs, create_dirs=True, write_metadata=True)
    config = ctx["config"]
    layout = ctx["layout"]
    metadata = ctx["metadata"]
    metadata_path = ctx["metadata_path"]
    month_window = ctx["month_window"]
    window_months = [pd.Period(f"{y:04d}-{m:02d}", freq="M") for y, m in month_window["months"]]

    def _sync_metadata() -> None:
        sync_run_metadata(metadata, metadata_path)

    # Directory aliases to keep output structure consistent with existing notebook runs.
    dirs = {
        "raw_cds": layout["raw"] / "cds",
        "raw_extracted": layout["intermediate"] / "cds_extracted",
        "masks_native": layout["rasters"] / "masks_native" / "spei",
        "masks_worldpop": layout["rasters"] / "masks_worldpop" / "spei",
        "pop_affected": layout["rasters"] / "pop_affected" / "spei",
        "qc_spei": layout["qc"] / "spei",
        "qc_preflight": layout["qc"] / "preflight",
        "logs": layout["logs"],
    }
    for p in dirs.values():
        p.mkdir(parents=True, exist_ok=True)

    cache_root = Path(config.output_root).resolve() / "_cache" / "water_scarcity_spei3" / iso3
    cache_dirs = {
        "cds_raw": cache_root / "cds_raw",
        "cds_extracted": cache_root / "cds_raw" / "extracted",
        "aoi": cache_root / "aoi",
    }
    for p in cache_dirs.values():
        p.mkdir(parents=True, exist_ok=True)

    geo = prepare_spei_geography(
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
    aoi_hash_path = cache_dirs["aoi"] / f"{iso3}_{admin_label}_union_bounds_hash.txt"
    aoi_hash_path.write_text(aoi_hash, encoding="utf-8")
    append_artifact(metadata, "aoi_bounds_hash", aoi_hash_path, "Admin bounds hash for SPEI CDS fetch area")

    # WorldPop base raster.
    with rasterio.open(options.worldpop_path) as wp:
        wp_arr = wp.read(1).astype("float64")
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
    worldpop_total = float(np.nansum(wp_arr[pop_valid_mask]))
    append_artifact(
        metadata, "worldpop_raster", options.worldpop_path, "Country WorldPop raster used as aggregation grid"
    )

    # Preflight coverage checks.
    sample_year = int(window_months[0].year)
    sample_month = int(window_months[0].month)
    wp_cov = check_worldpop_coverage((west, south, east, north), options.worldpop_path)
    sample_zip = dirs["logs"] / "preflight" / f"{iso3}_spei_sample_{sample_year}{sample_month:02d}.zip"
    sample_zip.parent.mkdir(parents=True, exist_ok=True)
    sample_req = spei_sample_request(sample_year, sample_month, cds_area)
    sample = run_cds_single_month_check(
        dataset="derived-drought-historical-monthly",
        request=sample_req,
        output_zip=sample_zip,
    )
    if not sample["ok"] or sample.get("sample_bounds_4326") is None:
        raise RuntimeError(f"SPEI preflight sample failed: {sample.get('error')}")
    spei_cov = bbox_coverage_report((west, south, east, north), tuple(sample["sample_bounds_4326"]))
    metadata["preflight_coverage"] = {
        "sample_year": sample_year,
        "sample_month": sample_month,
        "worldpop": wp_cov,
        "spei_sample": {
            **sample,
            "coverage_pct": float(spei_cov["coverage_pct"]),
            "full_coverage": bool(spei_cov["full_coverage"]),
        },
    }
    if options.require_full_preflight_coverage and not bool(spei_cov["full_coverage"]):
        _sync_metadata()
        raise RuntimeError(
            f"SPEI preflight coverage is not full ({spei_cov['coverage_pct']:.3f}%). "
            "Increase CDS buffer and rerun."
        )

    # Download monthly CDS files with consolidated -> intermediate fallback.
    dl_status_path = dirs["logs"] / "spei_download_status.json"
    dl_started = time.perf_counter()

    def _dl_status(
        stage: str, processed: int, total: int, success: int, failed: int, current: str | None = None
    ) -> None:
        elapsed = max(0.0, time.perf_counter() - dl_started)
        rate = (processed / elapsed) if elapsed > 0 else 0.0
        remaining = max(0, total - processed)
        eta = (remaining / rate) if rate > 0 else None
        _write_status(
            dl_status_path,
            {
                "stage": stage,
                "processed": int(processed),
                "total": int(total),
                "success": int(success),
                "failed": int(failed),
                "pct_complete": float((processed / total) * 100.0) if total else 100.0,
                "elapsed_seconds": float(round(elapsed, 2)),
                "rate_items_per_second": float(round(rate, 4)),
                "eta_seconds": None if eta is None else float(round(eta, 2)),
                "current": current,
            },
        )

    months = months_for_last_n(config.as_of_date, n_months=config.lookback_months)
    end_yyyymm = pd.to_datetime(config.as_of_date).strftime("%Y%m")
    cache_key = f"{iso3}_spei3_{aoi_hash}_{end_yyyymm}"
    manifest: list[dict[str, Any]] = []
    _dl_status("downloads", 0, len(months), 0, 0, None)
    ok_months = 0
    failed_months = 0

    for idx, (y, m) in enumerate(months, start=1):
        month_label = f"{y}-{m:02d}"
        month_ok = False
        cons_zip = cache_dirs["cds_raw"] / f"{cache_key}_{y}{m:02d}_consolidated_dataset.zip"
        if cons_zip.exists() and cons_zip.stat().st_size > 0:
            manifest.append(
                {
                    "year": y,
                    "month": f"{m:02d}",
                    "dataset_type": "consolidated_dataset",
                    "ok": True,
                    "error": None,
                    "path": str(cons_zip),
                    "cached": True,
                }
            )
            month_ok = True
        else:
            req_cons = {
                "variable": ["standardised_precipitation_evapotranspiration_index"],
                "accumulation_period": ["3"],
                "version": "1_0",
                "product_type": ["reanalysis"],
                "dataset_type": "consolidated_dataset",
                "year": [str(y)],
                "month": [f"{m:02d}"],
                "area": cds_area,
            }
            ok, err = download_cds("derived-drought-historical-monthly", req_cons, cons_zip)
            manifest.append(
                {
                    "year": y,
                    "month": f"{m:02d}",
                    "dataset_type": "consolidated_dataset",
                    "ok": bool(ok),
                    "error": err,
                    "path": str(cons_zip),
                    "cached": False,
                }
            )
            if ok:
                month_ok = True
            else:
                int_zip = cache_dirs["cds_raw"] / f"{cache_key}_{y}{m:02d}_intermediate_dataset.zip"
                if int_zip.exists() and int_zip.stat().st_size > 0:
                    manifest.append(
                        {
                            "year": y,
                            "month": f"{m:02d}",
                            "dataset_type": "intermediate_dataset",
                            "ok": True,
                            "error": None,
                            "path": str(int_zip),
                            "cached": True,
                        }
                    )
                    month_ok = True
                else:
                    req_int = req_cons.copy()
                    req_int["dataset_type"] = "intermediate_dataset"
                    ok2, err2 = download_cds("derived-drought-historical-monthly", req_int, int_zip)
                    manifest.append(
                        {
                            "year": y,
                            "month": f"{m:02d}",
                            "dataset_type": "intermediate_dataset",
                            "ok": bool(ok2),
                            "error": err2,
                            "path": str(int_zip),
                            "cached": False,
                        }
                    )
                    month_ok = bool(ok2)

        if month_ok:
            ok_months += 1
        else:
            failed_months += 1
        _dl_status("downloads", idx, len(months), ok_months, failed_months, month_label)

    manifest_path = ensure_downloads(manifest=manifest, kind="spei3", logs_dir=dirs["logs"])
    append_artifact(metadata, "cds_manifest_spei3", manifest_path, f"{len(manifest)} CDS request rows")
    ok_df = pd.DataFrame([m for m in manifest if m.get("ok")])
    if ok_df.empty:
        _sync_metadata()
        raise RuntimeError("All SPEI CDS monthly downloads failed.")
    chosen = (
        ok_df.sort_values(["year", "month", "dataset_type"])
        .groupby(["year", "month"], as_index=False)
        .first()
    )

    nc_paths: list[Path] = []
    _dl_status("extract", 0, len(chosen), 0, 0, None)
    extract_ok = 0
    extract_fail = 0
    for idx, (_, row) in enumerate(chosen.iterrows(), start=1):
        zpath = Path(str(row["path"]))
        extracted = extract_zip_to_dir(zpath, cache_dirs["cds_extracted"])
        if not extracted:
            extract_fail += 1
            _dl_status("extract", idx, len(chosen), extract_ok, extract_fail, zpath.name)
            _sync_metadata()
            raise RuntimeError(f"No NetCDFs extracted from {zpath}")
        extract_ok += 1
        nc_paths.extend(extracted)
        _dl_status("extract", idx, len(chosen), extract_ok, extract_fail, zpath.name)

    # Unique paths preserving order.
    seen = set()
    nc_unique: list[Path] = []
    for p in nc_paths:
        sp = str(p)
        if sp not in seen:
            seen.add(sp)
            nc_unique.append(Path(sp))
    nc_paths = nc_unique
    metadata["cds_downloads"] = {
        "dataset": "derived-drought-historical-monthly",
        "cache_key": cache_key,
        "months_target": [f"{y}-{m:02d}" for y, m in months],
        "months_selected": [f"{int(r.year)}-{int(r.month):02d}" for _, r in chosen.iterrows()],
        "n_nc_paths": int(len(nc_paths)),
        "progress_status_path": str(dl_status_path),
    }

    # Build monthly SPEI stack.
    das = []
    for p in nc_paths:
        ds = xr.open_dataset(p, decode_times=True, engine="netcdf4")
        da = ds[_find_spei_var(ds)]
        rename = {}
        if "latitude" in da.dims:
            rename["latitude"] = "lat"
        if "longitude" in da.dims:
            rename["longitude"] = "lon"
        if rename:
            da = da.rename(rename)
        for d in ("time", "lat", "lon"):
            if d not in da.dims:
                ds.close()
                raise KeyError(f"Expected dim '{d}' not found in {p.name}. Got {da.dims}")
        das.append(da)
        ds.close()
    spei = xr.concat(das, dim="time").sortby("time")
    _, idx = np.unique(spei["time"].values, return_index=True)
    spei = spei.isel(time=np.sort(idx)).sortby("time")
    spei = _ensure_rio_spatial_dims(spei)
    spei = spei.rio.write_crs("EPSG:4326", inplace=False)
    target_months = [str(p) for p in window_months]
    spei_months = spei["time"].dt.strftime("%Y-%m").values.tolist()
    spei = spei.isel(time=np.isin(spei_months, target_months)).sortby("time")
    if int(spei.sizes.get("time", 0)) == 0:
        _sync_metadata()
        raise RuntimeError("No SPEI months available after filtering to requested window.")

    # Clip to admin geometry.
    spei = _ensure_rio_spatial_dims(spei)
    spei_da = spei.rio.clip([mapping(country_geom_4326)], crs="EPSG:4326", drop=True, all_touched=True)
    spei_da = _ensure_rio_spatial_dims(spei_da)
    spei_da = spei_da.rio.write_crs("EPSG:4326", inplace=False)

    # Raster compute stage.
    raster_status_path = dirs["logs"] / "spei_raster_compute_status.json"
    raster_started = time.perf_counter()

    def _r_status(processed: int, total: int, current: str | None = None) -> None:
        elapsed = max(0.0, time.perf_counter() - raster_started)
        rate = (processed / elapsed) if elapsed > 0 else 0.0
        remaining = max(0, total - processed)
        eta = (remaining / rate) if rate > 0 else None
        _write_status(
            raster_status_path,
            {
                "stage": "raster_compute",
                "processed": int(processed),
                "total": int(total),
                "pct_complete": float((processed / total) * 100.0) if total else 100.0,
                "elapsed_seconds": float(round(elapsed, 2)),
                "rate_items_per_second": float(round(rate, 4)),
                "eta_seconds": None if eta is None else float(round(eta, 2)),
                "current": current,
            },
        )

    def _mask_da_transform(mask_da_2d) -> Any:
        lats = mask_da_2d["lat"].values
        lons = mask_da_2d["lon"].values
        dlat = float(np.abs(lats[1] - lats[0]))
        dlon = float(np.abs(lons[1] - lons[0]))
        north0 = float(np.max(lats) + dlat / 2.0)
        west0 = float(np.min(lons) - dlon / 2.0)
        return from_origin(west0, north0, dlon, dlat)

    products: dict[str, Any] = {}
    _r_status(0, len(thresholds), None)
    for idx, (key, thr) in enumerate(thresholds.items(), start=1):
        mask_native_da = (spei_da <= float(thr)).fillna(False).any(dim="time")
        src_mask_arr = mask_native_da.values.astype(np.uint8)
        src_transform = _mask_da_transform(mask_native_da)
        native_path = dirs["masks_native"] / f"spei_mask_{key}_native.tif"
        write_array_geotiff(
            native_path, src_mask_arr, transform=src_transform, crs="EPSG:4326", nodata=255, dtype="uint8"
        )
        mask_wp = reproject_array_to_grid(
            src_array=src_mask_arr,
            src_transform=src_transform,
            src_crs="EPSG:4326",
            dst_shape=(wp_profile["height"], wp_profile["width"]),
            dst_transform=wp_profile["transform"],
            dst_crs=wp_profile["crs"],
            src_nodata=255,
            dst_nodata=255,
            resampling="nearest",
        ).astype(np.uint8)
        mask_wp_path = dirs["masks_worldpop"] / f"spei_mask_{key}_worldpop.tif"
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
        pop_path = dirs["pop_affected"] / f"spei_pop_affected_{key}.tif"
        write_array_geotiff(
            pop_path,
            pop_affected,
            transform=wp_profile["transform"],
            crs=wp_profile["crs"],
            nodata=0.0,
            dtype="float32",
        )
        products[key] = {
            "threshold": float(thr),
            "mask_native_path": str(native_path),
            "mask_worldpop_path": str(mask_wp_path),
            "pop_affected_path": str(pop_path),
            "pop_affected_sum": float(np.nansum(pop_affected)),
        }
        _r_status(idx, len(thresholds), key)

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
        shapes=shapes,
        out_shape=wp_shape,
        transform=wp_transform,
        fill=0,
        dtype="int32",
        all_touched=False,
    )
    n_admin = len(admin_units_wp)
    pop_total_by_id = labelled_sum(admin_id_raster, wp_arr, n_labels=n_admin, valid_mask=pop_valid_mask)
    out = pd.DataFrame(
        {
            pcode_label: admin_units_wp[pcode_label].values,
            "admin_id": np.arange(1, n_admin + 1, dtype=int),
        }
    )
    out["pop_total"] = pop_total_by_id
    for key in thresholds.keys():
        pop_path = Path(products[key]["pop_affected_path"])
        with rasterio.open(pop_path) as src:
            arr = src.read(1).astype("float64")
            arr_nodata = src.nodata
            arr_ok = np.isfinite(arr)
            if arr_nodata is not None:
                arr_ok &= arr != float(arr_nodata)
            arr_ok &= arr >= 0
            pop_aff_by_id = labelled_sum(
                admin_id_raster,
                arr,
                n_labels=n_admin,
                valid_mask=pop_valid_mask & arr_ok,
            )
        col_pop = f"pop_affected_{key}"
        col_pct = f"pct_affected_{key}"
        out[col_pop] = pop_aff_by_id
        out[col_pct] = np.where(out["pop_total"] > 0, (out[col_pop] / out["pop_total"]) * 100.0, np.nan)
    default_key = options.default_threshold_key
    out = standardize_admin_summary(
        out,
        config=config,
        admin_level=adm_level,
        admin_pcode_column=pcode_label,
        population_total_column="pop_total",
        population_affected_column=f"pop_affected_{default_key}",
        pct_affected_column=f"pct_affected_{default_key}",
    )
    out_csv = layout["tables"] / f"{iso3}_{admin_label}_water_scarcity_spei3_{config.as_of_date}.csv"
    out.drop(columns=["admin_id"]).to_csv(out_csv, index=False)
    append_artifact(
        metadata, "admin_water_scarcity_table", out_csv, f"{admin_label.title()} SPEI exposure table"
    )
    append_artifact(
        metadata, f"{admin_label}_water_scarcity_table", out_csv, f"{admin_label.title()} SPEI exposure table"
    )
    if adm_level == 2:
        append_artifact(metadata, "admin2_water_scarcity_table", out_csv, "Admin2 SPEI exposure table")

    # QC summary CSV (kept small and deterministic for parity).
    qc_csv = dirs["qc_spei"] / f"{iso3}_spei_qc_{config.as_of_date}.csv"
    mask_pop_sum = float(out[f"pop_affected_{default_key}"].sum())
    qc_df = pd.DataFrame(
        [
            {
                "iso3": iso3,
                "as_of_date": config.as_of_date,
                "window_months": ", ".join(str(p) for p in window_months),
                "default_threshold_key": default_key,
                "default_threshold_value": float(thresholds[default_key]),
                "worldpop_total_pop": worldpop_total,
                "mask_pop_sum": mask_pop_sum,
                "pop_affected_sum": float(products[default_key]["pop_affected_sum"]),
                "mask_vs_pop_affected_diff": float(
                    mask_pop_sum - float(products[default_key]["pop_affected_sum"])
                ),
                "grid_alignment_ok": True,
                "worldpop_shape": str(wp_shape),
                "worldpop_crs": str(wp_crs),
                "worldpop_nodata": wp_nodata,
                "pop_aff_nodata": 0.0,
            }
        ]
    )
    qc_df.to_csv(qc_csv, index=False)
    append_artifact(metadata, "spei_qc_table", qc_csv, "SPEI QC summary table")

    metadata["pipeline"] = "water_scarcity_spei3"
    metadata["aoi"] = {
        "country_bounds_4326": {"west": west, "south": south, "east": east, "north": north},
        "cds_area": cds_area,
        "cds_buffer_deg": float(options.cds_buffer_deg),
        "bounds_hash": aoi_hash,
        "bounds_hash_path": str(aoi_hash_path),
    }
    metadata["worldpop"] = {
        "path": str(options.worldpop_path),
        "crs": str(wp_crs),
        "shape": [int(wp_shape[0]), int(wp_shape[1])],
        "nodata": wp_nodata,
        "total_pop_valid": worldpop_total,
    }
    metadata["spei_masks"] = {
        "thresholds": {k: float(v) for k, v in thresholds.items()},
        "default_key": default_key,
        "products": products,
        "window_months": [str(p) for p in window_months],
        "aggregation_rule": "any_month_spei_le_threshold",
        "progress_status_path": str(raster_status_path),
    }
    metadata["admin_table_spei"] = {
        "path": str(out_csv),
        "admin_layer": options.admin_layer,
        "admin_level": int(adm_level),
        "admin_pcode_column": pcode_label,
        f"n_{admin_label}": int(len(out)),
        "thresholds": {k: float(v) for k, v in thresholds.items()},
        "default_key": default_key,
        "window_months": [str(p) for p in window_months],
        "rule": "any_month_spei_le_threshold",
    }
    metadata[f"{admin_label}_table_spei"] = dict(metadata["admin_table_spei"])
    if adm_level == 2:
        metadata["admin2_table_spei"] = dict(metadata["admin_table_spei"])
    metadata["spei_qc_figures"] = {"qc_csv": str(qc_csv)}
    _sync_metadata()

    outputs = {
        "admin_table": str(out_csv),
        f"{admin_label}_table": str(out_csv),
        "qc_csv": str(qc_csv),
        "default_pop_affected_tif": products[default_key]["pop_affected_path"],
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
