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
    resource = files("wia_pipelines.hazards.earthquake").joinpath("default.yml")
    with resource.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if override_path:
        with Path(override_path).open(encoding="utf-8") as stream:
            config = _merge(config, yaml.safe_load(stream) or {})
    validate_config(config)
    return config


def validate_config(config: Mapping[str, Any]) -> None:
    shaking = config["shaking"]
    thresholds = [float(value) for value in shaking["sensitivity_thresholds_mmi"]]
    if thresholds != sorted(set(thresholds)) or not thresholds:
        raise ValueError("sensitivity_thresholds_mmi must be increasing and unique")
    if float(shaking["primary_threshold_mmi"]) not in thresholds:
        raise ValueError("primary_threshold_mmi must be included in sensitivity thresholds")
    if any(value < 1 or value > 12 for value in thresholds):
        raise ValueError("MMI thresholds must be within [1, 12]")
    if shaking.get("continuous_resampling") != "bilinear":
        raise ValueError("Version 0.1 supports bilinear continuous-MMI resampling only")
    if float(config["discovery"]["country_buffer_km"]) < 0:
        raise ValueError("country_buffer_km must be non-negative")
    if int(config["discovery"]["timeout_seconds"]) <= 0:
        raise ValueError("timeout_seconds must be positive")
    level = int(config["admin"]["level"])
    if not config["admin"]["fields"].get(f"adm{level}_pcode"):
        raise ValueError(f"admin.fields.adm{level}_pcode is required")


def config_hash(config: Mapping[str, Any]) -> str:
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()
