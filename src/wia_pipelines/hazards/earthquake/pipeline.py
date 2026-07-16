from __future__ import annotations

import json
import platform
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
from rasterio.features import geometry_mask
from shapely.geometry import box, mapping

from ...config import RunConfig, initialize_run_metadata, validate_run_metadata
from ...core.admin import build_admin_aoi
from ...core.assets import checksum_path, link_cached_asset, shared_cache_root, url_cache_key
from ...core.io_paths import append_artifact, build_run_layout, create_run_dirs
from ...core.pipeline import hazard_method, standardize_admin_summary
from ...core.raster_ops import reproject_array_to_grid, write_array_geotiff
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


def _actual_column(columns, configured: str | None) -> str | None:
    if not configured:
        return None
    if configured in columns:
        return configured
    return {str(column).lower(): str(column) for column in columns}.get(str(configured).lower())


def _load_admin(path: Path, iso3: str, config: dict[str, Any]) -> gpd.GeoDataFrame:
    level = int(config["level"])
    fields = config["fields"]
    kwargs = {"layer": config["layer"]} if config.get("layer") else {}
    try:
        admin = gpd.read_file(path, **kwargs)
    except Exception:
        if not kwargs:
            raise
        admin = gpd.read_file(path)
    if admin.empty or admin.crs is None:
        raise ValueError("Admin input must contain features and a declared CRS")
    for key, configured in list(fields.items()):
        actual = _actual_column(admin.columns, configured)
        if actual is not None:
            fields[key] = actual
    iso_field = fields.get("iso3")
    if iso_field in admin.columns:
        admin = admin.loc[admin[iso_field].astype(str).str.upper() == iso3.upper()].copy()
    elif fields.get("adm0_pcode") in admin.columns:
        field = fields["adm0_pcode"]
        admin = admin.loc[admin[field].astype(str).str[:3].str.upper() == iso3.upper()].copy()
    if admin.empty:
        raise ValueError(f"No admin features match ISO3 {iso3}")
    pcode = fields.get(f"adm{level}_pcode")
    if not pcode or pcode not in admin.columns:
        raise ValueError(f"Admin input is missing configured Admin-{level} key: {pcode}")
    if admin[pcode].isna().any() or admin[pcode].duplicated().any():
        raise ValueError(f"Admin-{level} P-codes must be present and unique")
    admin = admin.loc[admin.geometry.notna() & ~admin.geometry.is_empty].copy()
    admin.geometry = admin.geometry.make_valid()
    return admin.reset_index(drop=True)


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
    admin = _load_admin(inputs.admin, run.iso3, config["admin"])
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
    validate_inputs(inputs)
    layout = build_run_layout(run.output_root, run.hazard, run.iso3, run.run_id)
    create_run_dirs(layout)
    admin = _load_admin(inputs.admin, run.iso3, config["admin"])
    admin_4326 = admin.to_crs(4326)
    aoi = build_admin_aoi(admin_4326, buffer_km=run.buffer_km)

    with rasterio.open(inputs.worldpop) as source:
        population = source.read(1).astype("float32")
        population_transform = source.transform
        population_crs = source.crs
        population_shape = (source.height, source.width)
        population_nodata = source.nodata
    population_valid = np.isfinite(population) & (population >= 0)
    if population_nodata is not None:
        population_valid &= population != population_nodata

    discovery = config["discovery"]
    catalog_url = build_catalog_url(
        run.window_start.isoformat(),
        run.window_end.isoformat(),
        aoi["aoi_bounds"],
        discovery["catalog_url"],
    )
    usgs_cache = shared_cache_root(inputs.out, "usgs")
    catalog_cache_path = usgs_cache / "catalogues" / f"{url_cache_key(catalog_url)}.geojson"
    catalog, catalog_fetch = fetch_json_cached(
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
    event_rows: list[dict[str, Any]] = []
    included = 0
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
        actual, reason = is_actual_event(feature)
        if not actual:
            row["exclusion_reason"] = reason
            event_rows.append(row)
            continue
        if "shakemap" not in str(properties.get("types") or "").lower():
            row["exclusion_reason"] = "no_catalog_shakemap_reference"
            event_rows.append(row)
            continue
        detail_url = properties.get("detail")
        if not detail_url:
            row["exclusion_reason"] = "missing_event_detail_url"
            event_rows.append(row)
            continue
        detail_cache_path = usgs_cache / "events" / event_id / f"detail_{url_cache_key(str(detail_url))}.json"
        detail, detail_fetch = fetch_json_cached(
            str(detail_url),
            detail_cache_path,
            int(discovery["timeout_seconds"]),
            refresh=inputs.refresh_cache,
        )
        event_dir = layout["raw"] / "event_products" / event_id
        event_dir.mkdir(parents=True, exist_ok=True)
        link_cached_asset(detail_cache_path, event_dir / "detail.json")
        product = select_shakemap_product(detail)
        selected = None if product is None else select_grid_content(product)
        if selected is None or not selected[0].lower().endswith("grid.xml"):
            row["exclusion_reason"] = "no_supported_grid_xml"
            event_rows.append(row)
            continue
        content_name, content = selected
        if not content.get("url"):
            row["exclusion_reason"] = "grid_missing_url"
            event_rows.append(row)
            continue
        grid_cache_path = usgs_cache / "shakemaps" / f"{url_cache_key(str(content['url']))}.xml"
        downloaded = download_cached(
            str(content["url"]),
            grid_cache_path,
            int(discovery["timeout_seconds"]),
            refresh=inputs.refresh_cache,
        )
        grid_path = link_cached_asset(grid_cache_path, event_dir / "grid.xml")
        grid = parse_grid_xml(grid_path.read_bytes())
        bounds = rasterio.transform.array_bounds(grid.mmi.shape[0], grid.mmi.shape[1], grid.transform)
        if not box(*bounds).intersects(country_geometry):
            row["exclusion_reason"] = "shakemap_does_not_intersect_country"
            event_rows.append(row)
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
            event_rows.append(row)
            continue
        _annual_maximum(maximum, aligned)
        included += 1
        product_properties = product.get("properties") or {}
        row.update(
            status="included",
            exclusion_reason=None,
            shakemap_version=product_properties.get("version"),
            shakemap_status=product.get("status"),
            shakemap_update_time=product.get("updateTime"),
            product_content=content_name,
            product_url=content["url"],
            sha256=downloaded["sha256"],
            detail_asset_source=detail_fetch["source"],
            grid_asset_source=downloaded["source"],
        )
        event_rows.append(row)

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
    records = []
    for index, area in admin_population.iterrows():
        area_mask = geometry_mask(
            [mapping(area.geometry)],
            population_shape,
            population_transform,
            invert=True,
            all_touched=bool(config["admin"].get("all_touched", False)),
        )
        total = float(np.sum(population[area_mask & population_valid], dtype="float64"))
        record = {f"adm{level}_pcode": str(area[pcode_field]), "pop_total": total}
        for ancestor in range(level):
            field = fields.get(f"adm{ancestor}_pcode")
            record[f"adm{ancestor}_pcode"] = area[field] if field in area.index else None
        for suffix in ("name_en", "name_local"):
            field = fields.get(f"adm{level}_{suffix}")
            record[f"adm{level}_{suffix}"] = area[field] if field in area.index else None
        for threshold in thresholds:
            label = f"{threshold:g}".replace(".", "p")
            affected = float(np.sum(exposure_arrays[threshold][area_mask], dtype="float64"))
            record[f"pop_affected_mmi{label}"] = affected
            record[f"pct_affected_mmi{label}"] = 100 * affected / total if total else np.nan
        records.append(record)
    table = pd.DataFrame(records)
    primary_label = f"{primary:g}".replace(".", "p")
    table["pop_affected"] = table[f"pop_affected_mmi{primary_label}"]
    table["pct_affected"] = table[f"pct_affected_mmi{primary_label}"]
    national_total = float(table["pop_total"].sum())
    national_affected = float(table["pop_affected"].sum())
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
                layout["qc"],
                iso3=run.iso3,
                end_label=end_label,
                admin_level=level,
                primary_threshold=primary,
                national_pct=national_pct,
            )
        )

    metadata = initialize_run_metadata(run, paths=layout)
    method_definition = hazard_method("earthquake")
    metadata.update(
        {
            "pipeline": method_definition.pipeline,
            "method_version": method_definition.method_version,
            "population_rule": method_definition.population_rule,
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
            },
            "config": config,
            "config_hash": config_hash(config),
            "inputs": {
                "worldpop": {
                    "path": str(inputs.worldpop.resolve()),
                    "sha256": checksum_path(inputs.worldpop),
                },
                "admin": {"path": str(inputs.admin.resolve()), "sha256": checksum_path(inputs.admin)},
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
