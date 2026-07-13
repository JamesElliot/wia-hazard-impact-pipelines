from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any, Callable


def _require(name: str):
    import importlib

    return importlib.import_module(name)


def months_for_last_n(as_of: str, n_months: int = 12) -> list[tuple[int, int]]:
    if n_months < 1:
        raise ValueError(f"n_months must be >= 1, got {n_months}.")
    pd = _require("pandas")
    end = pd.to_datetime(as_of).to_period("M")
    return [(int((end - n).year), int((end - n).month)) for n in range(0, n_months)][::-1]


def download_cds(dataset: str, request: dict[str, Any], out_zip: Path) -> tuple[bool, str | None]:
    cdsapi = _require("cdsapi")
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    try:
        client = cdsapi.Client()
        result = client.retrieve(dataset, request)
        result.download(target=str(out_zip))
        return True, None
    except Exception as exc:  # pragma: no cover - network/auth failures are runtime dependent
        return False, str(exc)


def extract_zip_to_dir(zip_path: Path, out_dir: Path) -> list[Path]:
    out_subdir = out_dir / zip_path.stem
    out_subdir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(out_subdir)
    return sorted(out_subdir.rglob("*.nc"))


def ensure_downloads(
    manifest: list[dict[str, Any]],
    kind: str,
    logs_dir: Path,
    update_artifact: Callable[[str, Path, str], None] | None = None,
) -> Path:
    pd = _require("pandas")
    logs_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = logs_dir / f"cds_manifest_{kind}.csv"
    pd.DataFrame(manifest).to_csv(manifest_path, index=False)
    if update_artifact is not None:
        update_artifact(f"cds_manifest_{kind}", manifest_path, f"{len(manifest)} requests recorded")

    ok_count = sum(1 for row in manifest if row.get("ok"))
    if ok_count == 0:
        errors = [row.get("error") for row in manifest if row.get("error")]
        first_error = errors[0] if errors else "Unknown"
        raise RuntimeError(f"All CDS downloads failed for '{kind}'. Example error: {first_error}")
    return manifest_path
