from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_run_layout(output_root: Path, iso3: str, window_label: str, hazard: str) -> dict[str, Path]:
    """Canonical on-disk layout: outputs/<ISO3>/<WINDOW>/<hazard>/...

    This is the single source of truth for run directory shape; callers
    working from a RunConfig should go through config.build_run_paths
    instead of calling this directly.
    """
    hazard_norm = hazard.strip().lower()
    iso3_norm = iso3.strip().upper()
    base = Path(output_root) / iso3_norm / window_label / hazard_norm
    return {
        "base": base,
        "raw": base / "raw",
        "intermediate": base / "intermediate",
        "rasters": base / "rasters",
        "tables": base / "tables",
        "qc": base / "qc",
        "logs": base / "logs",
        "maps": base / "maps",
        "cache": Path(output_root) / "_cache" / iso3_norm / hazard_norm,
    }


def create_run_dirs(layout: dict[str, Path]) -> dict[str, Path]:
    for path in layout.values():
        ensure_dir(path)
    return layout


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def append_artifact(
    run_metadata: dict[str, Any],
    kind: str,
    path: Path,
    notes: str = "",
) -> None:
    run_metadata.setdefault("artifacts", [])
    run_metadata["artifacts"].append({"kind": kind, "path": str(path), "notes": notes})
