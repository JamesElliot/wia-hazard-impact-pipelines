from __future__ import annotations

from pathlib import Path

from wia_hazard_impacts.config import RunConfig
from wia_hazard_impacts.metadata.schema import write_run_metadata


def run(cfg: RunConfig) -> None:
    """Run pipeline (scaffold).

    TODO: move the logic from the corresponding notebook into this module,
    using shared helpers for alignment, masking, population affected, and
    admin2 zonal stats.
    """

    out_dir = Path(cfg.outputs.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_run_metadata(cfg, out_dir / "run_metadata.json", extra={"status": "scaffold"})
    raise NotImplementedError("Hazard pipeline not yet refactored from notebook")
