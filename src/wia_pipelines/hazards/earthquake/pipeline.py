from __future__ import annotations

import json
import platform
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
import rasterio
import shapely
from rasterio.features import geometry_mask, rasterize
from shapely.geometry import box, mapping

from ...config import RunConfig, validate_run_metadata
from ...core.admin import build_admin_aoi
from ...core.aggregation import labelled_sum
from ...core.assets import checksum_path, link_cached_asset, shared_cache_root, url_cache_key
from ...core.io_paths import append_artifact
from ...core.pipeline import build_hazard_run_context, standardize_admin_summary
from ...core.raster_ops import reproject_array_to_grid, write_array_geotiff
from .._admin_config import load_yaml_hazard_admin
from ._version import __version__
from .client import (
    build_catalog_url,
    download_cached,
    fetch_json_cached,
    is_actual_event,
    parse_grid_xml,
    select_grid_content,
    select_shakemap_product,
)
from .config import config_hash, load_config
from .visualize import write_run_maps


@dataclass(frozen=True)
class RunInputs:
    iso3: str
    window_end: str
    worldpop: Path
    admin: Path
    out: Path
    lookback_months: int = 12
    target_adm_level: int | None = None
    admin_layer: str | None = None
    config: Path | None = None
    refresh_cache: bool = False


def _configured(inputs: RunInputs) -> dict[str, Any]:
    config = load_config(inputs.config)
    config["temporal"]["window_months"] = int(inputs.lookback_months)
    if inputs.target_adm_level is not None:
        config["admin"]["level"] = int(inputs.target_adm_level)
    if inputs.admin_layer is not None:
        config["admin"]["layer"] = inputs.admin_layer
    elif not config["admin"].get("layer") and str(inputs.admin).lower().endswith(".zip"):
        config["admin"]["layer"] = f"admin{int(config['admin']['level'])}"
    return config


def validate_inputs(inputs: RunInputs) -> dict[str, Any]:
    config = _configured(inputs)
    for path in (inputs.worldpop, inputs.admin):
        if not Path(path).exists():
            raise FileNotFoundError(path)
    run = RunConfig(
        hazard="earthquake",
        iso3=inputs.iso3,
        as_of_date=inputs.window_end,
        lookback_months=int(inputs.lookback_months),
        output_root=inputs.out,
        target_adm_level=int(config["admin"]["level"]),
        buffer_km=float(config["discovery"]["country_buffer_km"]),
    )
    admin = load_yaml_hazard_admin(inputs.admin, run.iso3, config["admin"])
    with rasterio.open(inputs.worldpop) as population:
        if population.count != 1 or population.crs is None:
            raise ValueError("WorldPop must be a one-band raster with a CRS")
        population_meta = {
            "width": population.width,
            "height": population.height,
            "crs": str(population.crs),
            "nodata": population.nodata,
        }
    return {
        "iso3": run.iso3,
        "window_start": run.window_start.isoformat(),
        "window_end": run.window_end.isoformat(),
        "admin_features": len(admin),
        "population": population_meta,
        "config_hash": config_hash(config),
    }


def _annual_maximum(current: np.ndarray, candidate: np.ndarray) -> None:
    valid = np.isfinite(candidate)
    empty = valid & ~np.isfinite(current)
    overlap = valid & np.isfinite(current)
    current[empty] = candidate[empty]
    current[overlap] = np.maximum(current[overlap], candidate[overlap])


FETCH_WORKERS = 6
FETCH_RETRY_ATTEMPTS = 3
FETCH_RETRY_BACKOFF_SECONDS = 1.0


def _fetch_with_retry(fn, *args, **kwargs):
    """Retry a flaky USGS network call with exponential backoff (PERF-010).

    Wraps call sites (catalog/detail/grid fetches below) rather than
    `client.fetch_bytes`/`download_cached` themselves, so those primitives'
    existing no-auto-retry contract (see `test_earthquake_client.py`, which
    asserts a failed call raises rather than silently retrying) stays
    unchanged for any other caller. Only retries genuine transport-layer
    failures (timeout, connection/HTTP errors) -- a malformed-response
    ValueError, for instance, would just fail identically on every retry and
    shouldn't be retried.
    """
    last_exc: BaseException | None = None
    for attempt in range(FETCH_RETRY_ATTEMPTS):
        try:
            return fn(*args, **kwargs)
        except (urllib.error.URLError, TimeoutError) as exc:
            last_exc = exc
            if attempt < FETCH_RETRY_ATTEMPTS - 1:
                time.sleep(FETCH_RETRY_BACKOFF_SECONDS * (2**attempt))
    assert last_exc is not None
    raise last_exc


def run_pipeline(inputs: RunInputs) -> Path:
    config = _configured(inputs)
    run = RunConfig(
        hazard="earthquake",
        iso3=inputs.iso3,
        as_of_date=inputs.window_end,
        lookback_months=int(inputs.lookback_months),
        output_root=inputs.out,
        target_adm_level=int(config["admin"]["level"]),
        buffer_km=float(config["discovery"]["country_buffer_km"]),
    )
    for path in (inputs.worldpop, inputs.admin):
        if not Path(path).exists():
            raise FileNotFoundError(path)
    ctx = build_hazard_run_context(run, create_dirs=True, write_metadata=False)
    layout = ctx["layout"]
    # Admin is loaded exactly once here (PERF-003): this used to be loaded a second
    # time by a `validate_inputs(inputs)` call, which re-read and re-validated the
    # same multi-hundred-MB admin file `run_pipeline` was about to load anyway.
    admin = load_yaml_hazard_admin(inputs.admin, run.iso3, config["admin"])
    admin_4326 = admin.to_crs(4326)
    aoi = build_admin_aoi(admin_4326, buffer_km=run.buffer_km)

    with rasterio.open(inputs.worldpop) as source:
        if source.count != 1 or source.crs is None:
            raise ValueError("WorldPop must be a one-band raster with a CRS")
        population = source.read(1).astype("float32")
        population_transform = source.transform
        population_crs = source.crs
        population_shape = (source.height, source.width)
        population_nodata = source.nodata
    population_valid = np.isfinite(population) & (population >= 0)
    if population_nodata is not None:
        population_valid &= population != population_nodata
    population_raster_total = float(np.sum(population[population_valid], dtype="float64"))

    discovery = config["discovery"]
    catalog_url = build_catalog_url(
        run.window_start.isoformat(),
        run.window_end.isoformat(),
        aoi["aoi_bounds"],
        discovery["catalog_url"],
    )
    usgs_cache = shared_cache_root(inputs.out, "usgs")
    checksum_cache_dir = shared_cache_root(inputs.out, "checksums")
    catalog_cache_path = usgs_cache / "catalogues" / f"{url_cache_key(catalog_url)}.geojson"
    catalog, catalog_fetch = _fetch_with_retry(
        fetch_json_cached,
        catalog_url,
        catalog_cache_path,
        int(discovery["timeout_seconds"]),
        refresh=inputs.refresh_cache,
    )
    catalog_path = layout["raw"] / "usgs_catalogue.geojson"
    link_cached_asset(catalog_cache_path, catalog_path)

    primary = float(config["shaking"]["primary_threshold_mmi"])
    thresholds = tuple(float(value) for value in config["shaking"]["sensitivity_thresholds_mmi"])
    country_geometry = aoi["admin_union_geom"]
    country_mask = geometry_mask(
        [mapping(country_geometry)], population_shape, population_transform, invert=True
    )
    maximum = np.full(population_shape, np.nan, dtype="float32")

    # PERF-010: detail.json/grid.xml fetches for different events are
    # independent I/O, so they're prefetched concurrently below. Output
    # order/values must not depend on fetch completion order or thread
    # count, so the design is deliberately three separate phases:
    #  1. A single sequential pass over `catalog["features"]` builds every
    #     row dict up front, in catalog order, and appends it to
    #     `event_rows` immediately -- this fixes event_rows's final order
    #     before any concurrency happens; later phases only mutate these
    #     same dict objects in place, never reorder or re-append them.
    #  2. Concurrent detail-fetch, then concurrent grid-fetch, each via
    #     `ThreadPoolExecutor.map` (which yields results in the order tasks
    #     were submitted, i.e. catalog order, regardless of completion
    #     order -- no manual re-sorting needed).
    #  3. A final sequential pass does the local MMI processing and
    #     `_annual_maximum` accumulation; `_annual_maximum` is a pointwise
    #     max, so accumulating included events in any order gives the same
    #     result -- only the *set* of included events matters, not the
    #     order they're folded in.
    event_rows: list[dict[str, Any]] = []
    detail_candidates: list[dict[str, Any]] = []
    for feature in catalog.get("features", []):
        properties = feature.get("properties") or {}
        event_id = str(feature.get("id") or "unknown")
        row = {
            "event_id": event_id,
            "event_time_ms": properties.get("time"),
            "title": properties.get("title"),
            "magnitude": properties.get("mag"),
            "magnitude_type": properties.get("magType"),
            "depth_km": (feature.get("geometry") or {}).get("coordinates", [None, None, None])[2],
            "status": "excluded",
            "exclusion_reason": None,
        }
        event_rows.append(row)
        actual, reason = is_actual_event(feature)
        if not actual:
            row["exclusion_reason"] = reason
            continue
        if "shakemap" not in str(properties.get("types") or "").lower():
            row["exclusion_reason"] = "no_catalog_shakemap_reference"
            continue
        detail_url = properties.get("detail")
        if not detail_url:
            row["exclusion_reason"] = "missing_event_detail_url"
            continue
        detail_cache_path = usgs_cache / "events" / event_id / f"detail_{url_cache_key(str(detail_url))}.json"
        detail_candidates.append(
            {
                "row": row,
                "event_id": event_id,
                "detail_url": detail_url,
                "detail_cache_path": detail_cache_path,
            }
        )

    def _fetch_detail(candidate: dict[str, Any]):
        return _fetch_with_retry(
            fetch_json_cached,
            str(candidate["detail_url"]),
            candidate["detail_cache_path"],
            int(discovery["timeout_seconds"]),
            refresh=inputs.refresh_cache,
        )

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        detail_results = list(pool.map(_fetch_detail, detail_candidates))

    grid_candidates: list[dict[str, Any]] = []
    for candidate, (detail, detail_fetch) in zip(detail_candidates, detail_results):
        row = candidate["row"]
        event_id = candidate["event_id"]
        event_dir = layout["raw"] / "event_products" / event_id
        event_dir.mkdir(parents=True, exist_ok=True)
        link_cached_asset(candidate["detail_cache_path"], event_dir / "detail.json")
        product = select_shakemap_product(detail)
        selected = None if product is None else select_grid_content(product)
        if selected is None or not selected[0].lower().endswith("grid.xml"):
            row["exclusion_reason"] = "no_supported_grid_xml"
            continue
        content_name, content = selected
        if not content.get("url"):
            row["exclusion_reason"] = "grid_missing_url"
            continue
        grid_cache_path = usgs_cache / "shakemaps" / f"{url_cache_key(str(content['url']))}.xml"
        grid_candidates.append(
            {
                "row": row,
                "event_dir": event_dir,
                "product": product,
                "content_name": content_name,
                "content": content,
                "grid_cache_path": grid_cache_path,
                "detail_fetch": detail_fetch,
            }
        )

    def _fetch_grid(candidate: dict[str, Any]):
        return _fetch_with_retry(
            download_cached,
            str(candidate["content"]["url"]),
            candidate["grid_cache_path"],
            int(discovery["timeout_seconds"]),
            refresh=inputs.refresh_cache,
        )

    with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
        grid_results = list(pool.map(_fetch_grid, grid_candidates))

    included = 0
    for candidate, downloaded in zip(grid_candidates, grid_results):
        row = candidate["row"]
        grid_path = link_cached_asset(candidate["grid_cache_path"], candidate["event_dir"] / "grid.xml")
        grid = parse_grid_xml(grid_path.read_bytes())
        bounds = rasterio.transform.array_bounds(grid.mmi.shape[0], grid.mmi.shape[1], grid.transform)
        if not box(*bounds).intersects(country_geometry):
            row["exclusion_reason"] = "shakemap_does_not_intersect_country"
            continue
        aligned = reproject_array_to_grid(
            grid.mmi,
            grid.transform,
            grid.crs,
            population_shape,
            population_transform,
            population_crs,
            src_nodata=grid.nodata,
            dst_nodata=np.nan,
            resampling="bilinear",
        ).astype("float32")
        if not np.any(country_mask & np.isfinite(aligned) & (aligned >= primary)):
            row["exclusion_reason"] = "no_primary_threshold_shaking_in_country"
            continue
        _annual_maximum(maximum, aligned)
        included += 1
        product_properties = candidate["product"].get("properties") or {}
        row.update(
            status="included",
            exclusion_reason=None,
            shakemap_version=product_properties.get("version"),
            shakemap_status=candidate["product"].get("status"),
            shakemap_update_time=candidate["product"].get("updateTime"),
            product_content=candidate["content_name"],
            product_url=candidate["content"]["url"],
            sha256=downloaded["sha256"],
            detail_asset_source=candidate["detail_fetch"]["source"],
            grid_asset_source=downloaded["source"],
        )

    end_label = run.window_end.isoformat()
    max_path = layout["rasters"] / f"HIEQ_{run.iso3}_maximum_mmi_{end_label}.tif"
    write_array_geotiff(max_path, maximum, population_transform, population_crs, np.nan, "float32")
    mask_paths = {}
    exposure_arrays = {}
    for threshold in thresholds:
        label = f"{threshold:g}".replace(".", "p")
        threshold_mask = np.isfinite(maximum) & (maximum >= threshold)
        exposure_arrays[threshold] = np.where(population_valid & threshold_mask, population, 0.0)
        path = layout["rasters"] / f"HIEQ_{run.iso3}_mmi_ge_{label}_{end_label}.tif"
        write_array_geotiff(
            path, threshold_mask.astype("uint8"), population_transform, population_crs, 0, "uint8"
        )
        mask_paths[threshold] = path

    level = int(config["admin"]["level"])
    fields = config["admin"]["fields"]
    pcode_field = fields[f"adm{level}_pcode"]
    admin_population = admin.to_crs(population_crs).reset_index(drop=True)
    n_admin = len(admin_population)
    all_touched_admin = bool(config["admin"].get("all_touched", False))

    # PERF-006: rasterize admin polygons once (each pixel labelled 1..n_admin)
    # instead of an O(n_admin) geometry_mask() full-array pass per polygon.
    # Note: with all_touched=True, this assigns each shared-boundary pixel to
    # exactly one polygon (whichever rasterizes last), whereas the previous
    # per-polygon independent-mask loop could count that same pixel in both
    # adjacent polygons. This changed VCT/GRD's real admin1 population totals
    # by ~1.1% (benchmarked and accepted as the more correct, non-double-
    # counting behavior -- see PERF-006's entry in docs/repository-audit.md).
    admin_shapes = [(geom, i + 1) for i, geom in enumerate(admin_population.geometry)]
    admin_id = rasterize(
        shapes=admin_shapes,
        out_shape=population_shape,
        transform=population_transform,
        fill=0,
        dtype="int32",
        all_touched=all_touched_admin,
    )
    pop_total_by_id = labelled_sum(admin_id, population, n_labels=n_admin, valid_mask=population_valid)
    affected_by_id = {
        threshold: labelled_sum(admin_id, exposure_arrays[threshold], n_labels=n_admin)
        for threshold in thresholds
    }

    records = []
    for index, area in admin_population.iterrows():
        total = pop_total_by_id[index]
        record = {f"adm{level}_pcode": str(area[pcode_field]), "pop_total": total}
        for ancestor in range(level):
            field = fields.get(f"adm{ancestor}_pcode")
            record[f"adm{ancestor}_pcode"] = area[field] if field in area.index else None
        for suffix in ("name_en", "name_local"):
            field = fields.get(f"adm{level}_{suffix}")
            record[f"adm{level}_{suffix}"] = area[field] if field in area.index else None
        for threshold in thresholds:
            label = f"{threshold:g}".replace(".", "p")
            affected = affected_by_id[threshold][index]
            record[f"pop_affected_mmi{label}"] = affected
            record[f"pct_affected_mmi{label}"] = 100 * affected / total if total else np.nan
        records.append(record)
    table = pd.DataFrame(records)
    primary_label = f"{primary:g}".replace(".", "p")
    table["pop_affected"] = table[f"pop_affected_mmi{primary_label}"]
    table["pct_affected"] = table[f"pct_affected_mmi{primary_label}"]
    national_total = float(table["pop_total"].sum())
    national_affected = float(table["pop_affected"].sum())

    # METHOD-001: mirrors cyclone/pipeline.py's identical denominator-tolerance
    # guard (both hazards share the same "population.max_unassigned_fraction"
    # config key). Benchmarked against every existing real earthquake run
    # (VCT/GRD, all under configs/vct_grd_admin1_fields.yml's widened 5%
    # tolerance) before enabling: observed unassigned fractions were 2.39%/1.63%,
    # both comfortably inside that tolerance, so this enforcement changes no
    # existing real run's pass/fail outcome.
    assigned_fraction = national_total / population_raster_total if population_raster_total else None
    if assigned_fraction is None or population_raster_total <= 0:
        raise RuntimeError("No WorldPop population was found in the input raster")
    max_unassigned = float(config["population"]["max_unassigned_fraction"])
    if assigned_fraction < 1 - max_unassigned or assigned_fraction > 1 + max_unassigned:
        raise RuntimeError(
            "WorldPop/admin denominator mismatch: assigned population is "
            f"{assigned_fraction:.3%} of the input raster total; allowed tolerance is "
            f"±{max_unassigned:.1%}. Check country, boundary vintage, CRS and raster."
        )

    national_pct = 100 * national_affected / national_total if national_total else None
    table["deprivation"] = table["pct_affected"].gt(national_pct) if national_pct is not None else False
    table["flag_zero_population"] = table["pop_total"] <= 0
    table["flag_no_qualifying_events"] = included == 0
    table["run_id"] = run.run_id
    table = standardize_admin_summary(
        table,
        config=run,
        admin_level=level,
        admin_pcode_column=f"adm{level}_pcode",
        population_total_column="pop_total",
        population_affected_column="pop_affected",
        pct_affected_column="pct_affected",
    )

    table_path = layout["tables"] / f"HIEQ_{run.iso3}_{end_label}.csv"
    event_path = layout["qc"] / f"HIEQ_{run.iso3}_events_{end_label}.csv"
    table.to_csv(table_path, index=False, float_format="%.6f")
    pd.DataFrame(event_rows).to_csv(event_path, index=False)
    artifacts = {"admin_summary": table_path, "event_register": event_path}
    artifacts["maximum_mmi"] = max_path
    artifacts.update({f"mmi_ge_{threshold:g}_mask": path for threshold, path in mask_paths.items()})
    if config["outputs"].get("write_maps", True):
        artifacts.update(
            write_run_maps(
                admin,
                table,
                max_path,
                layout["maps"],
                iso3=run.iso3,
                end_label=end_label,
                admin_level=level,
                primary_threshold=primary,
                national_pct=national_pct,
            )
        )

    metadata = ctx["metadata"]  # already carries run_config/paths/pipeline/method_version/population_rule
    metadata.update(
        {
            "indicator": "HI-EQ",
            "pipeline_version": __version__,
            "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "iso3": run.iso3,
            "window": {"start": run.window_start.isoformat(), "end": end_label},
            "method": "USGS ShakeMap annual maximum MMI × WorldPop country-constrained",
            "country_summary": {
                "pop_total": national_total,
                "pop_affected": national_affected,
                "pct_affected": national_pct,
                "national_deprivation_threshold_pct": national_pct,
                "population_raster_total": population_raster_total,
                "population_assigned_fraction": assigned_fraction,
            },
            "config": config,
            "config_hash": config_hash(config),
            "inputs": {
                "worldpop": {
                    "path": str(inputs.worldpop.resolve()),
                    "sha256": checksum_path(inputs.worldpop, cache_dir=checksum_cache_dir),
                },
                "admin": {
                    "path": str(inputs.admin.resolve()),
                    "sha256": checksum_path(inputs.admin, cache_dir=checksum_cache_dir),
                },
                "usgs_catalogue": {
                    "query_url": catalog_url,
                    "retrieved_path": str(catalog_path),
                    "cache_path": str(catalog_cache_path),
                    "asset_source": catalog_fetch["source"],
                },
            },
            "qa": {
                "events_considered": len(event_rows),
                "events_included": included,
                "zero_event_result": included == 0,
                "refresh_cache": inputs.refresh_cache,
            },
            "software": {
                "python": platform.python_version(),
                "pandas": pd.__version__,
                "geopandas": gpd.__version__,
                "numpy": np.__version__,
                "rasterio": rasterio.__version__,
                "shapely": shapely.__version__,
                "pyproj": pyproj.__version__,
            },
        }
    )
    append_artifact(metadata, "usgs_catalogue", catalog_path)
    for kind, path in artifacts.items():
        append_artifact(metadata, kind, Path(path))
    validate_run_metadata(metadata)
    (layout["base"] / "run_metadata.json").write_text(
        json.dumps(metadata, indent=2, default=str) + "\n", encoding="utf-8"
    )
    source_path = layout["logs"] / f"HIEQ_{run.iso3}.source.md"
    source_path.write_text(_source_record(metadata), encoding="utf-8")
    return layout["base"]


def _source_record(metadata: dict[str, Any]) -> str:
    summary = metadata["country_summary"]
    pct = "NA" if summary["pct_affected"] is None else f"{summary['pct_affected']:.4f}%"
    return f"""# HI-EQ source record — {metadata["iso3"]}

- Window: {metadata["window"]["start"]} to {metadata["window"]["end"]} (inclusive)
- Method: {metadata["method"]}
- Primary threshold: MMI {metadata["config"]["shaking"]["primary_threshold_mmi"]:g}
- Population affected: {summary["pop_affected"]:.2f} of {summary["pop_total"]:.2f} ({pct})
- Events included: {metadata["qa"]["events_included"]} of {metadata["qa"]["events_considered"]} considered
- Run ID: `{metadata["run_id"]}`
- Config SHA-256: `{metadata["config_hash"]}`

## Interpretation and limitations

- Exposure to MMI VI or stronger is potential impact, not confirmed injury, displacement or WASH disruption.
- The annual maximum counts a residential population cell once even when multiple earthquakes affect it.
- Secondary hazards such as tsunami, liquefaction and landslides are excluded.
- ShakeMap accuracy varies with instrumental coverage and local ground-motion modelling.
"""
