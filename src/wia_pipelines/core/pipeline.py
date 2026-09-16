from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..config import RunConfig, build_run_paths, initialize_run_metadata, validate_run_metadata
from .assets import checksum_path, load_admin_source_manifest
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
        pipeline="water_scarcity_spei12",
        method_version="0.2.0",
        population_rule="WorldPop cells with SPEI12 at or below the reporting threshold in any month",
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
    "hydrodrought": HazardMethod(
        hazard="hydrodrought",
        pipeline="hydro_drought_glofas_sri",
        method_version="0.1.0",
        population_rule=(
            "WorldPop cells within a river-corridor buffer of a GloFAS reach with SRI3 at or below "
            "the reporting threshold for at least 2 consecutive months in the window"
        ),
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


class RunAlreadyCompleteError(RuntimeError):
    """Raised by build_hazard_run_context when skip_if_complete finds a valid prior SUCCESS run.

    Carries the existing run's metadata/layout so a caller (typically the CLI) can report on the
    already-complete run without needing to re-derive its paths.
    """

    def __init__(self, metadata: dict[str, Any], layout: dict[str, Path]) -> None:
        super().__init__(f"Run already completed successfully: {layout['base']}")
        self.metadata = metadata
        self.layout = layout


def run_already_complete(layout: dict[str, Path]) -> dict[str, Any] | None:
    """Return the existing run_metadata.json contents if it records a genuinely completed run.

    PROD-001: a run is only trusted as "complete" if its own metadata carries an explicit
    `"status": "SUCCESS"` marker written at that hazard's true end-of-run point -- every hazard
    pipeline calls `build_hazard_run_context(..., write_metadata=True)` at the very *start* of the
    run too, so a bare "run_metadata.json exists and is schema-valid" check alone would incorrectly
    treat a crashed/partial run as done. Returns None (not complete/trustable) on any missing file,
    parse error, or schema-validation failure, so a corrupted or in-progress run is always
    conservatively re-run rather than skipped.
    """

    metadata_path = layout["base"] / "run_metadata.json"
    if not metadata_path.exists():
        return None
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        validate_run_metadata(payload)
    except Exception:
        return None
    if payload.get("status") != "SUCCESS":
        return None
    return payload


def build_hazard_run_context(
    config: RunConfig,
    *,
    create_dirs: bool = True,
    write_metadata: bool = True,
    metadata_updates: Mapping[str, Any] | None = None,
    skip_if_complete: bool = False,
) -> dict[str, Any]:
    """Create the canonical layout and initial metadata used by every hazard.

    `skip_if_complete` is opt-in (default False, matching every existing caller's current
    behavior exactly): when True, and a prior run in this same target directory already recorded
    `"status": "SUCCESS"`, raises `RunAlreadyCompleteError` instead of proceeding -- see
    `run_already_complete()`. This is checked before any directory creation or metadata write, so
    it never touches a completed run's files.
    """

    method = hazard_method(config.hazard)
    layout = build_run_paths(config)
    if skip_if_complete:
        existing = run_already_complete(layout)
        if existing is not None:
            raise RunAlreadyCompleteError(existing, layout)
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


def build_admin_source(
    *,
    admin_path: str | Path,
    admin_level: int,
    unit_count: int,
    pcode_field: str,
    checksum_cache_dir: str | Path | None = None,
    asset_id: str | None = None,
) -> dict[str, Any]:
    """Build the `admin_source` provenance block for run_metadata.json.

    Raises `AdminSourceManifestError` (propagated from `load_admin_source_manifest`)
    if the admin dataset's sidecar `admin_source.json` manifest is missing or
    malformed -- callers should let this fail a run fast rather than catch it.
    """

    manifest = load_admin_source_manifest(admin_path)
    block: dict[str, Any] = {
        "authority": manifest["authority"],
        "vintage": manifest["vintage"],
        "access_date": manifest["access_date"],
        "path": str(Path(admin_path).resolve()),
        "sha256": checksum_path(admin_path, cache_dir=checksum_cache_dir),
        "admin_level": int(admin_level),
        "unit_count": int(unit_count),
        "pcode_field": str(pcode_field),
    }
    if asset_id:
        block["asset_id"] = asset_id
    return block


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
