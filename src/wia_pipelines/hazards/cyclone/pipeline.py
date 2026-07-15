from __future__ import annotations

import hashlib
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
from shapely.ops import unary_union

from ...config import RunConfig, initialize_run_metadata, validate_run_metadata
from ...core.io_paths import append_artifact, build_run_layout, create_run_dirs
from ...core.pipeline import hazard_method, standardize_admin_summary
from ._version import __version__
from .aggregate import aggregate_population
from .config import config_hash, load_config
from .footprints import build_wind_radii_footprint
from .gdacs import fetch_gdacs_fallbacks
from .tracks import (
    THRESHOLD_TO_KNOT,
    maximum_wind_knots,
    radii_completeness,
    read_ibtracs,
    rolling_window,
    select_candidate_points,
)
from .visualize import write_run_maps


@dataclass(frozen=True)
class RunInputs:
    iso3: str
    window_end: str
    ibtracs: Path
    worldpop: Path
    admin: Path
    out: Path
    lookback_months: int = 12
    config: Path | None = None
    gdacs_footprints: Path | None = None
    gdacs_auto: bool = False


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    paths = sorted(item for item in path.rglob("*") if item.is_file()) if path.is_dir() else [path]
    for item in paths:
        if path.is_dir():
            digest.update(str(item.relative_to(path)).encode())
        with item.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def _load_admin(path: Path, iso3: str, admin_config: dict[str, Any]) -> gpd.GeoDataFrame:
    fields = admin_config["fields"]
    level = int(admin_config["level"])
    read_kwargs = {"layer": admin_config["layer"]} if admin_config.get("layer") else {}
    admin = gpd.read_file(path, **read_kwargs)
    if admin.empty or admin.crs is None:
        raise ValueError("Admin input must contain features and a declared CRS")
    iso_field = fields.get("iso3")
    if iso_field in admin.columns:
        subset = admin.loc[admin[iso_field].astype(str).str.upper() == iso3.upper()].copy()
        if subset.empty:
            raise ValueError(f"No admin features match ISO3 {iso3} in field {iso_field}")
        admin = subset
    elif fields.get("adm0_pcode") in admin.columns:
        column = fields["adm0_pcode"]
        subset = admin.loc[admin[column].astype(str).str[:3].str.upper() == iso3.upper()].copy()
        if subset.empty:
            raise ValueError(f"No admin features match ISO3 {iso3} by {column} prefix")
        admin = subset
    pcode = fields.get(f"adm{level}_pcode")
    if not pcode or pcode not in admin.columns:
        raise ValueError(f"Admin input is missing configured admin-{level} key: {pcode}")
    if admin[pcode].isna().any() or admin[pcode].duplicated().any():
        raise ValueError(f"Admin-{level} P-codes must be present and unique")
    admin = admin.loc[admin.geometry.notna() & ~admin.geometry.is_empty].copy()
    admin.geometry = admin.geometry.make_valid()
    return admin.reset_index(drop=True)


def _load_gdacs(path: Path | None) -> gpd.GeoDataFrame | None:
    if path is None:
        return None
    data = gpd.read_file(path).to_crs(4326)
    required = {"SID", "threshold_kmh"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"GDACS fallback is missing columns: {sorted(missing)}")
    data["threshold_kmh"] = pd.to_numeric(data["threshold_kmh"], errors="coerce")
    if data["threshold_kmh"].isna().any():
        raise ValueError("GDACS fallback contains invalid threshold_kmh values")
    if not set(data["threshold_kmh"].astype(int)).issubset({63, 93, 119}):
        raise ValueError("GDACS fallback thresholds must map to 63, 93 or 119 km/h")
    if not data.geometry.geom_type.isin({"Polygon", "MultiPolygon"}).all():
        raise ValueError("GDACS fallback geometries must be polygons")
    return data


def _fallback_storm_ids(
    candidates: pd.DataFrame,
    bands: list[int],
    minimum: float,
) -> list[str]:
    result = []
    for sid, storm in candidates.groupby("SID", sort=True):
        max_wind = maximum_wind_knots(storm)
        needs_fallback = any(
            (max_wind is None or max_wind >= THRESHOLD_TO_KNOT[threshold])
            and radii_completeness(storm, threshold) < minimum
            for threshold in bands
        )
        if needs_fallback:
            result.append(str(sid))
    return result


def validate_inputs(inputs: RunInputs) -> dict[str, Any]:
    config = load_config(inputs.config)
    config["temporal"]["window_months"] = int(inputs.lookback_months)
    if inputs.gdacs_footprints and inputs.gdacs_auto:
        raise ValueError("Use either --gdacs-footprints or --gdacs-auto, not both")
    for path in (inputs.ibtracs, inputs.worldpop):
        if not Path(path).is_file():
            raise FileNotFoundError(path)
    if not Path(inputs.admin).exists():
        raise FileNotFoundError(inputs.admin)
    window = rolling_window(inputs.window_end, int(config["temporal"]["window_months"]))
    admin = _load_admin(inputs.admin, inputs.iso3, config["admin"])
    tracks = read_ibtracs(inputs.ibtracs, window)
    with rasterio.open(inputs.worldpop) as population:
        if population.count != 1 or population.crs is None:
            raise ValueError("WorldPop must be a one-band raster with a CRS")
        population_meta = {
            "width": population.width,
            "height": population.height,
            "crs": str(population.crs),
            "nodata": population.nodata,
        }
    gdacs = _load_gdacs(inputs.gdacs_footprints)
    return {
        "iso3": inputs.iso3.upper(),
        "window_start": window.start.date().isoformat(),
        "window_end": pd.Timestamp(inputs.window_end).date().isoformat(),
        "admin_features": len(admin),
        "in_window_track_points": len(tracks),
        "in_window_storms": int(tracks["SID"].nunique()) if not tracks.empty else 0,
        "gdacs_fallback_features": len(gdacs) if gdacs is not None else 0,
        "gdacs_auto_requested": inputs.gdacs_auto,
        "population": population_meta,
        "config_hash": config_hash(config),
    }


def run_pipeline(inputs: RunInputs) -> Path:
    config = load_config(inputs.config)
    config["temporal"]["window_months"] = int(inputs.lookback_months)
    iso3 = inputs.iso3.upper()
    window = rolling_window(inputs.window_end, int(config["temporal"]["window_months"]))
    end_label = pd.Timestamp(inputs.window_end).date().isoformat()
    run_config = RunConfig(
        hazard="cyclone",
        iso3=iso3,
        as_of_date=end_label,
        lookback_months=int(config["temporal"]["window_months"]),
        output_root=Path(inputs.out),
        target_adm_level=int(config["admin"]["level"]),
    )
    layout = build_run_layout(
        output_root=run_config.output_root,
        hazard=run_config.hazard,
        iso3=run_config.iso3,
        run_id=run_config.run_id,
    )
    create_run_dirs(layout)
    output_dir = layout["base"]

    fields = config["admin"]["fields"]
    admin = _load_admin(inputs.admin, iso3, config["admin"])
    tracks = read_ibtracs(inputs.ibtracs, window)
    candidates = select_candidate_points(tracks, admin, float(config["footprint"]["track_buffer_km"]))
    bands = [int(value) for value in config["footprint"]["severity_bands_kmh"]]
    primary = int(config["footprint"]["affected_threshold_kmh"])
    minimum = float(config["footprint"]["minimum_radii_completeness"])
    if inputs.gdacs_footprints and inputs.gdacs_auto:
        raise ValueError("Use either --gdacs-footprints or --gdacs-auto, not both")
    gdacs_path = inputs.gdacs_footprints
    gdacs_audit_path = None
    gdacs = _load_gdacs(gdacs_path)
    if inputs.gdacs_auto:
        fallback_sids = _fallback_storm_ids(candidates, bands, minimum)
        gdacs_path = layout["intermediate"] / f"HI06_{iso3}_gdacs_fallbacks_{end_label}.gpkg"
        gdacs_audit_path = layout["qc"] / f"HI06_{iso3}_gdacs_audit_{end_label}.csv"
        for stale_path in (gdacs_path, gdacs_audit_path):
            if stale_path.exists():
                stale_path.unlink()
        if fallback_sids:
            fetch_result = fetch_gdacs_fallbacks(
                candidates.loc[candidates["SID"].astype(str).isin(fallback_sids)],
                window,
                gdacs_path,
                gdacs_audit_path,
            )
            gdacs = fetch_result.footprints
        else:
            gdacs = None
            gdacs_path = None
            gdacs_audit_path = None

    footprint_rows = []
    audit_rows = []
    storm_primary: dict[str, Any] = {}
    missing_primary = []
    severity_incomplete = False
    for sid, storm in candidates.groupby("SID", sort=True):
        max_wind = maximum_wind_knots(storm)
        first_date = storm["ISO_TIME"].min()
        last_date = storm["ISO_TIME"].max()
        name = _first_text(storm, "NAME")
        basin = _first_text(storm, "BASIN")
        storm_results = {}
        completeness_by_threshold = {}
        gdacs_event_ids = set()
        fallback_thresholds = []
        qualifying = max_wind is None or max_wind >= THRESHOLD_TO_KNOT[primary]
        for threshold in bands:
            expected = max_wind is None or max_wind >= THRESHOLD_TO_KNOT[threshold]
            result = build_wind_radii_footprint(
                storm,
                threshold,
                float(config["footprint"]["interpolation_spacing_km"]),
                int(config["footprint"]["angular_step_degrees"]),
                float(config["footprint"]["maximum_interpolation_gap_hours"]),
            )
            completeness_by_threshold[threshold] = result.completeness
            geometry = result.geometry if result.completeness >= minimum else None
            method = "wind_radii" if geometry is not None else None
            if (
                geometry is None
                and expected
                and gdacs is not None
                and "gdacs" in config["footprint"].get("fallback_order", [])
            ):
                match = gdacs.loc[
                    (gdacs["SID"].astype(str) == str(sid))
                    & (gdacs["threshold_kmh"].round().astype("Int64") == threshold)
                ]
                if not match.empty:
                    geometry = match.geometry.union_all()
                    method = "gdacs"
                    fallback_thresholds.append(threshold)
                    if "gdacs_eventid" in match:
                        gdacs_event_ids.update(match["gdacs_eventid"].dropna().astype(int).astype(str))
            if geometry is not None:
                storm_results[threshold] = geometry
                footprint_rows.append(
                    {
                        "SID": sid,
                        "name": name,
                        "threshold_kmh": threshold,
                        "method": method,
                        "radii_completeness": result.completeness,
                        "agencies": ",".join(result.agencies),
                        "native_threshold_kmh": (
                            int(match["native_threshold_kmh"].dropna().iloc[0])
                            if method == "gdacs"
                            and "native_threshold_kmh" in match
                            and not match["native_threshold_kmh"].dropna().empty
                            else threshold
                        ),
                        "gdacs_eventid": (",".join(sorted(gdacs_event_ids)) if method == "gdacs" else None),
                        "geometry": geometry,
                    }
                )
            elif expected and threshold != primary:
                severity_incomplete = True
        if not qualifying and primary not in storm_results:
            status = "below_primary_threshold"
        elif primary in storm_results:
            status = "complete_with_fallback" if primary in fallback_thresholds else "complete"
            storm_primary[str(sid)] = storm_results[primary]
        else:
            status = "missing_primary_footprint"
            missing_primary.append(str(sid))
        audit_rows.append(
            {
                "SID": sid,
                "name": name,
                "basin": basin,
                "start_date": first_date.isoformat(),
                "end_date": last_date.isoformat(),
                "max_wind_knots": max_wind,
                "status": status,
                "flag_provisional": _is_provisional(storm, last_date, window.end),
                "fallback_thresholds_kmh": ",".join(map(str, fallback_thresholds)) or None,
                "gdacs_eventids": ",".join(sorted(gdacs_event_ids)) or None,
                **{
                    f"radii_completeness_{threshold}": completeness_by_threshold[threshold]
                    for threshold in bands
                },
            }
        )

    allow_incomplete = bool(config["footprint"].get("allow_incomplete", False))
    if missing_primary and not allow_incomplete:
        raise RuntimeError(
            "No adequate primary footprint for candidate storm(s) "
            f"{', '.join(missing_primary)}. Supply GDACS polygons or explicitly set "
            "footprint.allow_incomplete=true for a flagged partial result."
        )

    band_geometries = {
        threshold: unary_union(
            [row["geometry"] for row in footprint_rows if row["threshold_kmh"] == threshold]
        )
        if any(row["threshold_kmh"] == threshold for row in footprint_rows)
        else None
        for threshold in bands
    }
    mask_path = (
        layout["rasters"] / f"HI06_{iso3}_mask_{end_label}.tif"
        if config["outputs"].get("write_mask", True)
        else None
    )
    aggregation = aggregate_population(
        admin,
        inputs.worldpop,
        band_geometries,
        storm_primary,
        fields,
        primary,
        int(config["admin"]["level"]),
        mask_path,
        all_touched_population=bool(config["population"].get("all_touched", False)),
        all_touched_admin=bool(config["admin"].get("all_touched", False)),
    )
    assigned_fraction = aggregation.country_summary["population_assigned_fraction"]
    if assigned_fraction is None or aggregation.country_summary["pop_total"] <= 0:
        raise RuntimeError("No WorldPop population was assigned to the selected admin boundaries")
    max_unassigned = float(config["population"]["max_unassigned_fraction"])
    if assigned_fraction < 1 - max_unassigned or assigned_fraction > 1 + max_unassigned:
        raise RuntimeError(
            "WorldPop/admin denominator mismatch: assigned population is "
            f"{assigned_fraction:.3%} of the input raster total; allowed tolerance is "
            f"±{max_unassigned:.1%}. Check country, boundary vintage, CRS and raster."
        )

    run_id = run_config.run_id
    table = aggregation.table
    used_primary_fallback = any(
        row["method"] == "gdacs" and row["threshold_kmh"] == primary for row in footprint_rows
    )
    used_any_fallback = any(row["method"] == "gdacs" for row in footprint_rows)
    table["flag_windradii"] = (
        "incomplete" if missing_primary else "fallback" if used_primary_fallback else "complete"
    )
    table["flag_provisional"] = any(row["flag_provisional"] for row in audit_rows)
    table["flag_adminfallback"] = False
    table["flag_severity_incomplete"] = severity_incomplete
    table["flag_method_fallback"] = used_any_fallback
    table["flag_zero_population"] = table["pop_total"] <= 0
    table["run_id"] = run_id

    table = standardize_admin_summary(
        table,
        config=run_config,
        admin_level=int(config["admin"]["level"]),
        admin_pcode_column=f"adm{int(config['admin']['level'])}_pcode",
        population_total_column="pop_total",
        population_affected_column="pop_affected",
        pct_affected_column="pct_affected",
    )

    csv_path = layout["tables"] / f"HI06_{iso3}_{end_label}.csv"
    storm_path = layout["qc"] / f"HI06_{iso3}_storms_{end_label}.csv"
    table.to_csv(csv_path, index=False, float_format="%.6f")
    audit_columns = [
        "SID",
        "name",
        "basin",
        "start_date",
        "end_date",
        "max_wind_knots",
        "status",
        "flag_provisional",
        *[f"radii_completeness_{threshold}" for threshold in bands],
        "fallback_thresholds_kmh",
        "gdacs_eventids",
    ]
    pd.DataFrame(audit_rows, columns=audit_columns).to_csv(storm_path, index=False)

    if config["outputs"].get("write_maps", True):
        if mask_path is None:
            raise ValueError("outputs.write_maps=true requires outputs.write_mask=true")
        map_paths = write_run_maps(
            admin,
            candidates,
            table,
            inputs.worldpop,
            mask_path,
            layout["qc"],
            iso3=iso3,
            end_label=end_label,
            window_start=window.start.date().isoformat(),
            primary_threshold=primary,
            admin_level=int(config["admin"]["level"]),
        )
    else:
        map_paths = {}
    footprint_path = None
    if footprint_rows and config["outputs"].get("write_footprints", True):
        footprints = gpd.GeoDataFrame(footprint_rows, geometry="geometry", crs=4326)
        footprint_path = layout["intermediate"] / f"HI06_{iso3}_footprints_{end_label}.gpkg"
        footprints.to_file(
            footprint_path,
            layer="footprints",
            driver="GPKG",
        )

    artifact_paths = {
        "admin_summary": csv_path,
        "storm_audit": storm_path,
    }
    if mask_path is not None:
        artifact_paths["hazard_mask"] = mask_path
    artifact_paths.update(map_paths)
    if footprint_path is not None:
        artifact_paths["cyclone_footprints"] = footprint_path
    if gdacs_audit_path is not None and Path(gdacs_audit_path).exists():
        artifact_paths["gdacs_audit"] = gdacs_audit_path
    manifest = _manifest(
        inputs,
        config,
        run_config,
        layout,
        window,
        aggregation.country_summary,
        audit_rows,
        missing_primary,
        severity_incomplete,
        gdacs_path if gdacs_path and Path(gdacs_path).exists() else None,
        gdacs_audit_path,
        artifact_paths,
    )
    manifest_path = output_dir / "run_metadata.json"
    validate_run_metadata(manifest)
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
    source_path = layout["logs"] / f"HI06_{iso3}.source.md"
    source_path.write_text(_source_markdown(manifest), encoding="utf-8")
    return output_dir


def _first_text(frame: pd.DataFrame, column: str) -> str | None:
    if column not in frame:
        return None
    values = frame[column].dropna().astype(str)
    return values.iloc[0] if not values.empty else None


def _is_provisional(storm: pd.DataFrame, last_date: pd.Timestamp, window_end: pd.Timestamp) -> bool:
    if "TRACK_TYPE" in storm:
        values = storm["TRACK_TYPE"].dropna().astype(str).str.upper()
        if values.str.contains("PROVISIONAL", regex=False).any():
            return True
        if values.eq("MAIN").any():
            return False
    if "USA_AGENCY" in storm:
        agencies = storm["USA_AGENCY"].dropna().astype(str).str.lower()
        if agencies.str.contains("tcvitals", regex=False).any():
            return True
    # Conservative fallback for older exports that omit TRACK_TYPE.
    return bool(last_date >= window_end - pd.DateOffset(years=2))


def _manifest(
    inputs,
    config,
    run_config,
    layout,
    window,
    country_summary,
    audit_rows,
    missing,
    severity_incomplete,
    gdacs_path=None,
    gdacs_audit_path=None,
    artifact_paths=None,
):
    input_paths = {
        "ibtracs": Path(inputs.ibtracs),
        "worldpop": Path(inputs.worldpop),
        "admin": Path(inputs.admin),
    }
    if gdacs_path:
        input_paths["gdacs_footprints"] = Path(gdacs_path)
    if gdacs_audit_path and Path(gdacs_audit_path).exists():
        input_paths["gdacs_audit"] = Path(gdacs_audit_path)
    metadata = initialize_run_metadata(run_config, paths=layout)
    method_definition = hazard_method("cyclone")
    metadata.update(
        {
            "pipeline": method_definition.pipeline,
            "method_version": method_definition.method_version,
            "population_rule": method_definition.population_rule,
            "indicator": "HI-06",
            "pipeline_version": __version__,
            "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "iso3": inputs.iso3.upper(),
            "window": {"start": window.start.date().isoformat(), "end": window.end.date().isoformat()},
            "method": (
                "IBTrACS observed wind-radii swath with GDACS wind-buffer fallback × "
                "WorldPop country-constrained"
                if any(row.get("fallback_thresholds_kmh") for row in audit_rows)
                else "IBTrACS observed wind-radii swath × WorldPop country-constrained"
            ),
            "country_summary": country_summary,
            "config": config,
            "config_hash": config_hash(config),
            "inputs": {
                key: {"path": str(path.resolve()), "sha256": _checksum(path)}
                for key, path in input_paths.items()
            },
            "qa": {
                "candidate_storms": len(audit_rows),
                "missing_primary_footprints": missing,
                "severity_incomplete": severity_incomplete,
                "external_event_crosscheck": (
                    "gdacs_auto_fallback"
                    if inputs.gdacs_auto and gdacs_audit_path and Path(gdacs_audit_path).exists()
                    else "gdacs_auto_not_required"
                    if inputs.gdacs_auto
                    else "not_run_local_pipeline"
                ),
                "applicability_gate": "not_run_upstream_required",
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
    for kind, path in (artifact_paths or {}).items():
        append_artifact(metadata, kind, Path(path))
    return metadata


def _source_markdown(manifest: dict[str, Any]) -> str:
    summary = manifest["country_summary"]
    pct = "NA" if summary["pct_affected"] is None else f"{summary['pct_affected']:.4f}%"
    return (
        f"""# HI-06 source record — {manifest["iso3"]}

- Window: {manifest["window"]["start"]} to {manifest["window"]["end"]} (inclusive)
- Method: {manifest["method"]}
- Primary threshold: {manifest["config"]["footprint"]["affected_threshold_kmh"]} km/h
- Population affected (country total): {summary["pop_affected"]:.2f} of {summary["pop_total"]:.2f} ({pct})
- Run ID: `{manifest["run_id"]}`
- Config SHA-256: `{manifest["config_hash"]}`

## Input provenance

"""
        + "\n".join(
            f"- {name}: `{details['path']}` — SHA-256 `{details['sha256']}`"
            for name, details in manifest["inputs"].items()
        )
        + """

## Quality and limitations

- The event footprint is based on observed IBTrACS quadrant wind radii, with GDACS wind buffers used only where recorded in the footprint and storm-audit products.
- GIRI/GCHD is the HE-13 exposure-family anchor, not an event input to this run.
- Rainfall and surge are not unioned into the baseline footprint; flood overlap belongs to HI-05.
- External GDACS/EM-DAT event-list QA and the long-term applicability gate are recorded in the run manifest and must be completed for a production release.
- Recent IBTrACS records may be provisional and should be rerun after archive revision.
"""
    )
