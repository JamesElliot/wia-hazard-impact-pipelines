from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .core.cds import (
    download_cds as _download_cds,
    ensure_downloads as _ensure_downloads,
    extract_zip_to_dir as _extract_zip_to_dir,
    months_for_last_n,
)
from .core.io_paths import ensure_dir as _ensure_dir


def ensure_dir(path: Path) -> Path:
    return _ensure_dir(path)


def assert_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing {label}: {path.resolve()}")


def months_for_last_12(as_of: str) -> list[tuple[int, int]]:
    return months_for_last_n(as_of=as_of, n_months=12)


def download_cds(dataset: str, request: dict, out_zip: Path) -> tuple[bool, str | None]:
    return _download_cds(dataset=dataset, request=request, out_zip=out_zip)


def extract_zip_to_dir(zip_path: Path, out_dir: Path) -> list[Path]:
    return _extract_zip_to_dir(zip_path=zip_path, out_dir=out_dir)


def update_run_metadata_artifact_dict(
    run_metadata: dict[str, Any],
    key: str,
    path: Path,
    note: str | None = None,
    metadata_path: Path | None = None,
) -> None:
    run_metadata.setdefault("artifacts", {})
    run_metadata["artifacts"][key] = {"path": str(path), "note": note}
    if metadata_path is not None:
        metadata_path.write_text(json.dumps(run_metadata, indent=2))


def update_run_metadata_artifact_list(
    run_metadata: dict[str, Any],
    kind: str,
    path: Path,
    notes: str = "",
    metadata_path: Path | None = None,
    record_artifact: Callable[[str, Path, str], None] | None = None,
) -> None:
    run_metadata.setdefault("artifacts", [])
    run_metadata["artifacts"].append({"kind": kind, "path": str(path), "notes": notes})
    if record_artifact is not None:
        record_artifact(kind, path, notes)
    if metadata_path is not None:
        metadata_path.write_text(json.dumps(run_metadata, indent=2))


def ensure_downloads(
    manifest: list[dict[str, Any]],
    kind: str,
    logs_dir: Path,
    update_artifact: Callable[[str, Path, str], None] | None = None,
) -> Path:
    return _ensure_downloads(
        manifest=manifest,
        kind=kind,
        logs_dir=logs_dir,
        update_artifact=update_artifact,
    )
