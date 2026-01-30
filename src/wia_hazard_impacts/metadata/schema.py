from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import json

from wia_hazard_impacts.config import RunConfig


def now_utc_iso() -> str:
    """UTC timestamp suitable for metadata."""

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_run_metadata(
    cfg: RunConfig,
    out_path: Path,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Write standard run metadata.

    Keep this stable; downstream WIA country models can rely on it.
    """

    payload: Dict[str, Any] = {
        "created_utc": now_utc_iso(),
        "iso3": cfg.iso3,
        "window": asdict(cfg.window),
        "hazard": {"name": cfg.hazard.name, "params": cfg.hazard.params},
        "inputs": {
            "admin2_path": str(cfg.inputs.admin2_path),
            "admin2_key": cfg.inputs.admin2_key,
            "worldpop_path": str(cfg.inputs.worldpop_path),
        },
        "outputs": {"out_dir": str(cfg.outputs.out_dir)},
    }

    if extra:
        payload.update(extra)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
