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


def download_month_with_fallback(
    dataset: str,
    request_builder: Callable[[int, int, str], dict[str, Any]],
    consolidated_zip: Path,
    intermediate_zip: Path,
    manifest_key: str,
    year: int,
    month: int,
) -> tuple[bool, list[dict[str, Any]]]:
    """Download one month's CDS asset, consolidated tier first, falling back
    to the intermediate tier -- checking the on-disk cache at each tier
    before issuing a new request.

    ``request_builder(year, month, tier)`` returns the full CDS request dict
    for that tier, where ``tier`` is ``"consolidated_dataset"`` or
    ``"intermediate_dataset"``. ``manifest_key`` is the field name the
    caller's manifest rows use for the tier value (hazards differ here --
    e.g. ``"dataset_type"`` vs ``"product_type"``).

    Returns ``(month_ok, manifest_rows)``.
    """
    manifest_rows: list[dict[str, Any]] = []

    def _try_tier(tier: str, zip_path: Path) -> bool:
        if zip_path.exists() and zip_path.stat().st_size > 0:
            manifest_rows.append(
                {
                    "year": year,
                    "month": f"{month:02d}",
                    manifest_key: tier,
                    "ok": True,
                    "error": None,
                    "path": str(zip_path),
                    "cached": True,
                }
            )
            return True
        request = request_builder(year, month, tier)
        ok, err = download_cds(dataset, request, zip_path)
        manifest_rows.append(
            {
                "year": year,
                "month": f"{month:02d}",
                manifest_key: tier,
                "ok": bool(ok),
                "error": err,
                "path": str(zip_path),
                "cached": False,
            }
        )
        return bool(ok)

    if _try_tier("consolidated_dataset", consolidated_zip):
        return True, manifest_rows
    if _try_tier("intermediate_dataset", intermediate_zip):
        return True, manifest_rows
    return False, manifest_rows


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
