from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


@dataclass(frozen=True)
class Window:
    """Analysis window in ISO dates (YYYY-MM-DD)."""

    start: str
    end: str


@dataclass(frozen=True)
class Inputs:
    """Common required input paths."""

    admin2_path: Path
    admin2_key: str
    worldpop_path: Path


@dataclass(frozen=True)
class Outputs:
    """Output settings."""

    out_dir: Path


@dataclass(frozen=True)
class HazardSpec:
    """Which hazard pipeline to run and its parameters."""

    name: str
    params: Dict[str, Any]


@dataclass(frozen=True)
class RunConfig:
    """Top-level run configuration shared across hazards."""

    iso3: str
    window: Window
    inputs: Inputs
    outputs: Outputs
    hazard: HazardSpec


def load_config(path: str | Path) -> RunConfig:
    """Load RunConfig from a YAML file."""

    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict):
        raise ValueError(f"Config must be a mapping. Got: {type(raw)}")

    # Basic validation with clear error messages
    iso3 = str(raw.get("iso3", "")).upper()
    if len(iso3) != 3:
        raise ValueError("'iso3' must be a 3-letter ISO3 code")

    w = raw.get("window") or {}
    window = Window(start=str(w.get("start")), end=str(w.get("end")))

    i = raw.get("inputs") or {}
    inputs = Inputs(
        admin2_path=Path(i.get("admin2_path")),
        admin2_key=str(i.get("admin2_key")),
        worldpop_path=Path(i.get("worldpop_path")),
    )

    o = raw.get("outputs") or {}
    outputs = Outputs(out_dir=Path(o.get("out_dir")))

    h = raw.get("hazard") or {}
    hazard = HazardSpec(name=str(h.get("name")), params=dict(h.get("params") or {}))

    return RunConfig(iso3=iso3, window=window, inputs=inputs, outputs=outputs, hazard=hazard)
