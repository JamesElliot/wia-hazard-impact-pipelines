from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import jsonschema


SUPPORTED_HAZARDS = {"cyclone", "drought", "flood", "heat", "violence"}


def _validate_iso3(iso3: str) -> str:
    value = (iso3 or "").strip().upper()
    if len(value) != 3 or not value.isalpha():
        raise ValueError(f"iso3 must be a 3-letter country code, got '{iso3}'.")
    return value


def _parse_iso_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except Exception as exc:
        raise ValueError(f"{field_name} must be ISO format YYYY-MM-DD, got '{value}'.") from exc


def _subtract_months(d: date, months: int) -> date:
    year = d.year
    month = d.month - months
    while month <= 0:
        month += 12
        year -= 1
    # Keep day in range for new month.
    if month in {1, 3, 5, 7, 8, 10, 12}:
        max_day = 31
    elif month in {4, 6, 9, 11}:
        max_day = 30
    else:
        leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
        max_day = 29 if leap else 28
    day = min(d.day, max_day)
    return date(year, month, day)


@dataclass(frozen=True)
class RunConfig:
    hazard: str
    iso3: str
    as_of_date: str
    lookback_months: int = 12
    output_root: Path = Path("./outputs")
    target_adm_level: int = 2
    buffer_km: float = 0.0

    def __post_init__(self) -> None:
        hazard_norm = (self.hazard or "").strip().lower()
        if hazard_norm not in SUPPORTED_HAZARDS:
            raise ValueError(
                f"Unsupported hazard '{self.hazard}'. Expected one of: {sorted(SUPPORTED_HAZARDS)}."
            )
        if self.lookback_months < 1:
            raise ValueError(f"lookback_months must be >= 1, got {self.lookback_months}.")
        if self.target_adm_level < 0 or self.target_adm_level > 3:
            raise ValueError(f"target_adm_level must be between 0 and 3, got {self.target_adm_level}.")
        if self.buffer_km < 0:
            raise ValueError(f"buffer_km must be >= 0, got {self.buffer_km}.")

        object.__setattr__(self, "hazard", hazard_norm)
        object.__setattr__(self, "iso3", _validate_iso3(self.iso3))
        object.__setattr__(self, "as_of_date", self.window_end.isoformat())
        object.__setattr__(self, "output_root", Path(self.output_root))

    @property
    def window_end(self) -> date:
        return _parse_iso_date(self.as_of_date, field_name="as_of_date")

    @property
    def window_start(self) -> date:
        return _subtract_months(self.window_end, self.lookback_months) + timedelta(days=1)

    @property
    def run_id(self) -> str:
        return (
            f"{self.iso3}_{self.window_start.isoformat()}_"
            f"{self.window_end.isoformat()}_m{self.lookback_months}_{self.hazard}"
        )


def build_run_paths(config: RunConfig) -> dict[str, Path]:
    root = Path(config.output_root)
    base = root / config.hazard / config.iso3 / config.run_id
    return {
        "base": base,
        "raw": base / "raw",
        "intermediate": base / "intermediate",
        "rasters": base / "rasters",
        "tables": base / "tables",
        "qc": base / "qc",
        "logs": base / "logs",
        "cache": root / "_cache" / config.hazard / config.iso3,
    }


def initialize_run_metadata(
    config: RunConfig,
    paths: dict[str, Path] | None = None,
    created_utc: str | None = None,
) -> dict[str, Any]:
    resolved_paths = paths or build_run_paths(config)
    created = created_utc or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return {
        "schema_version": "1.0.0",
        "run_id": config.run_id,
        "created_utc": created,
        "run_config": {
            "hazard": config.hazard,
            "iso3": config.iso3,
            "as_of_date": config.window_end.isoformat(),
            "lookback_months": config.lookback_months,
            "window_start": config.window_start.isoformat(),
            "window_end": config.window_end.isoformat(),
            "target_adm_level": config.target_adm_level,
            "buffer_km": config.buffer_km,
        },
        "paths": {k: str(v) for k, v in resolved_paths.items()},
        "artifacts": [],
    }


def _default_schema_path() -> Path:
    # repo root / schemas / run_metadata.schema.json
    return Path(__file__).resolve().parents[2] / "schemas" / "run_metadata.schema.json"


def validate_run_metadata(
    metadata: dict[str, Any],
    schema_path: str | Path | None = None,
) -> None:
    schema_file = Path(schema_path) if schema_path else _default_schema_path()
    run_schema = json.loads(schema_file.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(run_schema)
    jsonschema.validate(instance=metadata, schema=run_schema)
