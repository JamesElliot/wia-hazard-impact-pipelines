"""Shared YAML-config helpers for the cyclone and earthquake hazards.

These two hazards use a two-tier YAML `default.yml` + optional override
config, distinct from the ``RunConfig`` dataclass the other five hazards
use. ``merge_config``/``config_hash`` are the load-mechanics shared between
them; each hazard keeps its own ``validate_config`` (genuinely different
rules per hazard) local to its own ``config.py``.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Mapping


def merge_config(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(base))
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = merge_config(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def config_hash(config: Mapping[str, Any]) -> str:
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()
