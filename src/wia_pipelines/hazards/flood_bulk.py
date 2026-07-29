from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import RunConfig, build_run_paths
from .flood import FloodPipelineRunOptions, FloodRunInputs, run_flood_pipeline


SUMMARY_FIELDS = [
    "iso3",
    "year",
    "window_start",
    "window_end",
    "status",
    "reused_existing",
    "run_dir",
    "flood_days_tif",
    "flood_mask_tif",
    "admin_table",
    "population_affected",
    "population_affected_pct",
    "elapsed_seconds",
    "error",
]


@dataclass(frozen=True)
class FloodBulkRunOptions:
    iso3: str
    start_year: int
    end_year: int
    output_root: Path
    admin_path: Path
    worldpop_path: Path
    target_adm_level: int = 2
    admin_layer: str = "admin2"
    iso3_field: str = "iso3"
    stac_api_url: str = "https://stac.eodc.eu/api/v1"
    collection_id: str = "GFM"
    asset_key: str = "ensemble_flood_extent"
    worldpop_coverage_min_pct: float = 98.0
    worldpop_coverage_hard_min_pct: float = 50.0
    flood_stac_coverage_min_pct: float = 99.999
    flood_stac_coverage_hard_min_pct: float = 50.0
    flood_binary_threshold_days: int = 0
    chunk_y: int = 1024
    chunk_x: int = 1024
    resume: bool = True
    continue_on_error: bool = True

    def __post_init__(self) -> None:
        iso3 = str(self.iso3).strip().upper()
        if len(iso3) != 3 or not iso3.isalpha():
            raise ValueError(f"iso3 must be a 3-letter country code, got '{self.iso3}'.")
        if int(self.start_year) > int(self.end_year):
            raise ValueError("start_year must be less than or equal to end_year.")
        if int(self.start_year) < 2015:
            raise ValueError("start_year must be 2015 or later for the GFM archive.")
        object.__setattr__(self, "iso3", iso3)
        object.__setattr__(self, "output_root", Path(self.output_root).expanduser().resolve())
        object.__setattr__(self, "admin_path", Path(self.admin_path).expanduser().resolve())
        object.__setattr__(self, "worldpop_path", Path(self.worldpop_path).expanduser().resolve())


def calendar_year_windows(start_year: int, end_year: int) -> list[tuple[int, str, str]]:
    """Return inclusive calendar-year windows as year/start/end tuples."""

    start = int(start_year)
    end = int(end_year)
    if start > end:
        raise ValueError("start_year must be less than or equal to end_year.")
    return [(year, f"{year}-01-01", f"{year}-12-31") for year in range(start, end + 1)]


def _run_paths(options: FloodBulkRunOptions, year: int) -> dict[str, Path]:
    config = RunConfig(
        hazard="flood",
        iso3=options.iso3,
        as_of_date=f"{year}-12-31",
        lookback_months=12,
        output_root=options.output_root,
        target_adm_level=options.target_adm_level,
    )
    layout = build_run_paths(config)
    window_start = config.window_start.isoformat()
    window_end = config.window_end.isoformat()
    admin_label = f"admin{options.target_adm_level}"
    return {
        "run_dir": layout["base"],
        "metadata": layout["base"] / "run_metadata.json",
        "flood_days_tif": layout["rasters"]
        / "flood"
        / f"{options.iso3}_flood_days_{window_start}_{window_end}.tif",
        "flood_mask_tif": layout["rasters"]
        / "flood"
        / f"{options.iso3}_flood_any_{window_start}_{window_end}.tif",
        "admin_table": layout["tables"]
        / f"{options.iso3}_{admin_label}_flood_exposure_{window_start}_{window_end}.csv",
    }


def completed_flood_year(options: FloodBulkRunOptions, year: int) -> dict[str, Any] | None:
    """Return a normalized result when all required annual outputs already exist."""

    paths = _run_paths(options, year)
    required = [
        paths["metadata"],
        paths["flood_days_tif"],
        paths["flood_mask_tif"],
        paths["admin_table"],
    ]
    if not all(path.is_file() and path.stat().st_size > 0 for path in required):
        return None
    metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
    population = metadata.get("flood_pop_affected", {})
    return {
        "run_dir": str(paths["run_dir"]),
        "flood_days_tif": str(paths["flood_days_tif"]),
        "flood_mask_tif": str(paths["flood_mask_tif"]),
        "admin_table": str(paths["admin_table"]),
        "population_affected": population.get("pop_affected_sum"),
        "population_affected_pct": population.get("pop_affected_pct"),
    }


def build_flood_bulk_plan(options: FloodBulkRunOptions) -> list[dict[str, Any]]:
    """Describe annual work without contacting STAC or changing run outputs."""

    plan = []
    for year, window_start, window_end in calendar_year_windows(options.start_year, options.end_year):
        existing = completed_flood_year(options, year) if options.resume else None
        plan.append(
            {
                "iso3": options.iso3,
                "year": year,
                "window_start": window_start,
                "window_end": window_end,
                "status": "reusable" if existing is not None else "pending",
                "run_dir": str(_run_paths(options, year)["run_dir"]),
            }
        )
    return plan


def _write_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def run_flood_bulk(options: FloodBulkRunOptions) -> Path:
    """Run one standard 12-month flood analysis per calendar year."""

    if not options.admin_path.is_file():
        raise FileNotFoundError(f"Admin boundaries not found: {options.admin_path}")
    if not options.worldpop_path.is_file():
        raise FileNotFoundError(f"WorldPop raster not found: {options.worldpop_path}")

    summary_path = (
        options.output_root
        / "batch"
        / "flood"
        / f"{options.iso3}_flood_{options.start_year}_{options.end_year}_summary.csv"
    )
    rows: list[dict[str, Any]] = []

    for year, window_start, window_end in calendar_year_windows(options.start_year, options.end_year):
        started = time.monotonic()
        row: dict[str, Any] = {
            "iso3": options.iso3,
            "year": year,
            "window_start": window_start,
            "window_end": window_end,
            "status": "running",
            "reused_existing": False,
            "run_dir": str(_run_paths(options, year)["run_dir"]),
            "flood_days_tif": None,
            "flood_mask_tif": None,
            "admin_table": None,
            "population_affected": None,
            "population_affected_pct": None,
            "elapsed_seconds": None,
            "error": None,
        }
        try:
            result = completed_flood_year(options, year) if options.resume else None
            if result is not None:
                row["status"] = "success"
                row["reused_existing"] = True
            else:
                pipeline_result = run_flood_pipeline(
                    FloodPipelineRunOptions(
                        inputs=FloodRunInputs(
                            iso3=options.iso3,
                            as_of_date=window_end,
                            lookback_months=12,
                            output_root=options.output_root,
                            target_adm_level=options.target_adm_level,
                        ),
                        admin_path=options.admin_path,
                        worldpop_path=options.worldpop_path,
                        admin_layer=options.admin_layer,
                        iso3_field=options.iso3_field,
                        stac_api_url=options.stac_api_url,
                        collection_id=options.collection_id,
                        asset_key=options.asset_key,
                        worldpop_coverage_min_pct=options.worldpop_coverage_min_pct,
                        worldpop_coverage_hard_min_pct=options.worldpop_coverage_hard_min_pct,
                        flood_stac_coverage_min_pct=options.flood_stac_coverage_min_pct,
                        flood_stac_coverage_hard_min_pct=options.flood_stac_coverage_hard_min_pct,
                        flood_binary_threshold_days=options.flood_binary_threshold_days,
                        chunk_y=options.chunk_y,
                        chunk_x=options.chunk_x,
                    )
                )
                outputs = pipeline_result["outputs"]
                result = {
                    "run_dir": pipeline_result["run_dir"],
                    "flood_days_tif": outputs["flood_days_tif"],
                    "flood_mask_tif": outputs["flood_mask_tif"],
                    "admin_table": outputs["admin_table"],
                }
                completed = completed_flood_year(options, year)
                if completed is not None:
                    result.update(completed)
                row["status"] = "success"
            row.update(result)
        except Exception as exc:
            row["status"] = "failed"
            row["error"] = f"{type(exc).__name__}: {exc}"
            if not options.continue_on_error:
                row["elapsed_seconds"] = round(time.monotonic() - started, 3)
                rows.append(row)
                _write_summary(summary_path, rows)
                raise
        row["elapsed_seconds"] = round(time.monotonic() - started, 3)
        rows.append(row)
        _write_summary(summary_path, rows)

    return summary_path
