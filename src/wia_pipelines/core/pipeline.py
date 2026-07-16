from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..config import RunConfig, build_run_paths, initialize_run_metadata, validate_run_metadata
from .io_paths import append_artifact, create_run_dirs, write_json


@dataclass(frozen=True)
class HazardMethod:
    """Stable identifiers and reporting rule for a hazard pipeline."""

    hazard: str
    pipeline: str
    method_version: str
    population_rule: str


HAZARD_METHODS: dict[str, HazardMethod] = {
    "cyclone": HazardMethod(
        hazard="cyclone",
        pipeline="cyclone_ibtracs_wind_radii",
        method_version="0.1.0",
        population_rule="WorldPop cells inside the union of observed 34-knot wind-radius swaths",
    ),
    "drought": HazardMethod(
        hazard="drought",
        pipeline="water_scarcity_spei3",
        method_version="0.1.0",
        population_rule="WorldPop cells with SPEI3 at or below the reporting threshold in any month",
    ),
    "earthquake": HazardMethod(
        hazard="earthquake",
        pipeline="earthquake_usgs_shakemap",
        method_version="0.1.0",
        population_rule="WorldPop cells whose maximum USGS ShakeMap intensity reaches MMI VI",
    ),
    "flood": HazardMethod(
        hazard="flood",
        pipeline="gfm_flood",
        method_version="0.1.0",
        population_rule="WorldPop cells with flooded-day count above the reporting threshold",
    ),
    "heat": HazardMethod(
        hazard="heat",
        pipeline="extreme_heat_utci",
        method_version="0.1.0",
        population_rule="WorldPop cells exceeding the UTCI threshold for the consecutive-day duration",
    ),
    "violence": HazardMethod(
        hazard="violence",
        pipeline="violence_acled_proximity",
        method_version="0.1.0",
        population_rule="WorldPop cells in buffered ACLED event footprints meeting the event-count threshold",
    ),
}


def hazard_method(hazard: str) -> HazardMethod:
    try:
        return HAZARD_METHODS[hazard.strip().lower()]
    except KeyError as exc:
        raise ValueError(f"No method definition registered for hazard '{hazard}'.") from exc


def build_hazard_run_context(
    config: RunConfig,
    *,
    create_dirs: bool = True,
    write_metadata: bool = True,
    metadata_updates: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create the canonical layout and initial metadata used by every hazard."""

    method = hazard_method(config.hazard)
    layout = build_run_paths(config)
    if create_dirs:
        create_run_dirs(layout)

    metadata = initialize_run_metadata(config, paths=layout)
    metadata.update(
        {
            "pipeline": method.pipeline,
            "method_version": method.method_version,
            "population_rule": method.population_rule,
        }
    )
    if metadata_updates:
        metadata.update(dict(metadata_updates))
    validate_run_metadata(metadata)

    metadata_path = layout["base"] / "run_metadata.json"
    if write_metadata:
        write_json(metadata_path, metadata)
    return {
        "config": config,
        "layout": layout,
        "metadata": metadata,
        "metadata_path": metadata_path,
        "method": method,
    }


def sync_run_metadata(metadata: dict[str, Any], metadata_path: Path) -> None:
    validate_run_metadata(metadata)
    write_json(metadata_path, metadata)


def record_artifact(
    metadata: dict[str, Any],
    kind: str,
    path: str | Path,
    notes: str = "",
) -> None:
    append_artifact(metadata, kind, Path(path), notes)


def standardize_admin_summary(
    table,
    *,
    config: RunConfig,
    admin_level: int,
    admin_pcode_column: str,
    population_total_column: str,
    population_affected_column: str,
    pct_affected_column: str,
    hazard_data_coverage: float | None = None,
    population_data_coverage: float | None = None,
):
    """Add the cross-hazard output contract without removing compatibility fields."""

    required = {
        admin_pcode_column,
        population_total_column,
        population_affected_column,
        pct_affected_column,
    }
    missing = sorted(required - set(table.columns))
    if missing:
        raise KeyError(f"Cannot standardize admin summary; missing columns: {missing}")

    result = table.copy()
    method = hazard_method(config.hazard)
    result["iso3"] = config.iso3
    result["admin_level"] = int(admin_level)
    result["admin_pcode"] = result[admin_pcode_column]
    result["period_start"] = config.window_start.isoformat()
    result["period_end"] = config.window_end.isoformat()
    result["hazard"] = method.hazard
    result["method_version"] = method.method_version
    result["population_total"] = result[population_total_column]
    result["population_affected"] = result[population_affected_column]
    result["pct_affected"] = result[pct_affected_column]
    result["hazard_data_coverage"] = (
        float("nan") if hazard_data_coverage is None else float(hazard_data_coverage)
    )
    result["population_data_coverage"] = (
        float("nan") if population_data_coverage is None else float(population_data_coverage)
    )
    return result
