from __future__ import annotations

import copy
import hashlib
import json
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping

import yaml


def _merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config(override_path: Path | None = None) -> dict[str, Any]:
    resource = files("wia_pipelines.hazards.cyclone").joinpath("default.yml")
    with resource.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if override_path:
        with Path(override_path).open(encoding="utf-8") as stream:
            override = yaml.safe_load(stream) or {}
        config = _merge(config, override)
    validate_config(config)
    return config


def validate_config(config: Mapping[str, Any]) -> None:
    fp = config["footprint"]
    if fp.get("method") != "wind_radii":
        raise ValueError("Version 0.1 implements footprint.method=wind_radii only")
    bands = [int(value) for value in fp.get("severity_bands_kmh", [])]
    if bands != sorted(set(bands)) or not bands:
        raise ValueError("severity_bands_kmh must be a non-empty, increasing unique list")
    if any(value not in {63, 93, 119} for value in bands):
        raise ValueError("wind_radii supports only native IBTrACS contours 63, 93 and 119 km/h")
    if int(fp.get("affected_threshold_kmh", 0)) not in bands:
        raise ValueError("affected_threshold_kmh must be included in severity_bands_kmh")
    completeness = float(fp.get("minimum_radii_completeness", 0))
    if not 0 < completeness <= 1:
        raise ValueError("minimum_radii_completeness must be in (0, 1]")
    if float(fp.get("interpolation_spacing_km", 0)) <= 0:
        raise ValueError("interpolation_spacing_km must be positive")
    if float(fp.get("maximum_interpolation_gap_hours", 0)) <= 0:
        raise ValueError("maximum_interpolation_gap_hours must be positive")
    angular_step = int(fp.get("angular_step_degrees", 0))
    if angular_step <= 0 or 90 % angular_step:
        raise ValueError("angular_step_degrees must be a positive divisor of 90")
    unassigned = float(config["population"].get("max_unassigned_fraction", -1))
    if not 0 <= unassigned < 1:
        raise ValueError("population.max_unassigned_fraction must be in [0, 1)")
    admin = config["admin"]
    level = int(admin.get("level", -1))
    if level < 0:
        raise ValueError("admin.level must be a non-negative integer")
    pcode = admin.get("fields", {}).get(f"adm{level}_pcode")
    if not pcode:
        raise ValueError(f"admin.fields.adm{level}_pcode is required")


def config_hash(config: Mapping[str, Any]) -> str:
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()
