from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter
from typing import Any


def make_progress_writer(status_path: Path, stage: str, total: int):
    """Build a lightweight closure that writes JSON progress snapshots.

    Shared by every hazard pipeline's long-running download/raster loops.
    ``total`` is fixed for the lifetime of the returned closure -- construct
    a new writer (pointed at the same or a different status file) for each
    distinct processing stage with its own item count.
    """
    status_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = perf_counter()
    total = max(0, int(total))

    def _write(processed: int, ok: int = 0, failed: int = 0, current: str | None = None) -> dict[str, Any]:
        processed_i = max(0, int(processed))
        elapsed = perf_counter() - started_at
        rate = (processed_i / elapsed) if elapsed > 0 else 0.0
        remaining = max(0, total - processed_i)
        eta_seconds = (remaining / rate) if rate > 0 else None
        payload = {
            "stage": stage,
            "processed": processed_i,
            "total": total,
            "ok": int(ok),
            "failed": int(failed),
            "pct_complete": (float(processed_i) / float(total) * 100.0) if total else 100.0,
            "elapsed_seconds": round(float(elapsed), 2),
            "rate_items_per_second": round(float(rate), 4),
            "eta_seconds": None if eta_seconds is None else round(float(eta_seconds), 2),
            "current": current,
        }
        status_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    return _write
