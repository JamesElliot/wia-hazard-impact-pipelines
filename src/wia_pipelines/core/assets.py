from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import date
from pathlib import Path


DEFAULT_ADMIN_PATH = Path("./data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip")

_VINTAGE_PATTERN = re.compile(r"^[A-Z]+[0-9]{4}-(0[1-9]|1[0-2])$")


class AdminSourceManifestError(Exception):
    """Raised when the admin-boundary sidecar provenance manifest is missing
    or malformed. Distinct from FileNotFoundError/JSONDecodeError so a
    caller can tell "the admin dataset itself is missing" apart from "the
    admin dataset is present but its provenance manifest is not" -- the two
    require different fixes.
    """
DEFAULT_WORLDPOP_DIR = Path("./data/population")
DEFAULT_IBTRACS_DIR = Path("./data/cyclone")
DEFAULT_HYDRORIVERS_PATH = Path("./data/HydroRIVERS_v10/HydroRIVERS_v10.gdb")
DEFAULT_HYDROLAKES_PATH = Path("./data/HydroLAKES_polys_v10/HydroLAKES_polys_v10.gdb")


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def find_admin_path_for_iso3(iso3: str, registry_dir: str | Path | None = None) -> Path | None:
    """Look up a per-country COD-AB override registered under `registry_dir`
    (default: DEFAULT_ADMIN_PATH's parent, i.e. ./data/cod-ab).

    Each subdirectory may hold its own `admin_source.json` sidecar with a
    `"countries"` object keyed by ISO3 (see data/cod-ab/mli_sdn_moz_lbn/
    admin_source.json for the reference shape); a match returns the sibling
    `admin_boundaries.gpkg`. Returns None if no override is registered for
    `iso3`, so callers fall back to DEFAULT_ADMIN_PATH.
    """

    iso3_norm = str(iso3).strip().upper()
    base = _resolved(registry_dir or DEFAULT_ADMIN_PATH.parent)
    if not base.is_dir():
        return None
    for manifest_path in sorted(base.glob("*/admin_source.json")):
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        countries = raw.get("countries") if isinstance(raw, dict) else None
        if not isinstance(countries, dict) or iso3_norm not in countries:
            continue
        candidate = manifest_path.parent / "admin_boundaries.gpkg"
        if candidate.exists():
            return candidate
    return None


def resolve_admin_path(
    admin_path: str | Path | None = None,
    iso3: str | None = None,
    registry_dir: str | Path | None = None,
) -> Path:
    """Resolve the administrative-boundary asset without requiring it at parse time.

    An explicit `admin_path` always wins (unchanged behavior for every existing
    caller). Otherwise, when `iso3` is given, a per-country COD-AB override
    registered under `registry_dir` (see `find_admin_path_for_iso3`) takes
    precedence over DEFAULT_ADMIN_PATH -- this is how MLI/SDN/MOZ/LBN pick up
    their dedicated COD-AB download instead of the shared global asset.
    """

    if admin_path is not None:
        return _resolved(admin_path)
    if iso3:
        override = find_admin_path_for_iso3(iso3, registry_dir=registry_dir)
        if override is not None:
            return override
    return _resolved(DEFAULT_ADMIN_PATH)


def admin_source_manifest_path(admin_path: str | Path) -> Path:
    """Sidecar provenance manifest sibling to a resolved admin-boundary asset."""

    return _resolved(admin_path).parent / "admin_source.json"


def load_admin_source_manifest(admin_path: str | Path) -> dict[str, str]:
    """Load and validate the admin_source.json sidecar next to `admin_path`.

    Returns `{"authority": ..., "vintage": ..., "access_date": ...}`. Raises
    AdminSourceManifestError (never a bare FileNotFoundError/JSONDecodeError)
    if the manifest is missing, unparseable, or any field is missing or
    invalid -- callers should let this propagate to fail a new run fast.
    """

    manifest_path = admin_source_manifest_path(admin_path)
    if not manifest_path.exists():
        raise AdminSourceManifestError(
            f"Admin-boundary provenance manifest not found: {manifest_path}. "
            "Create it with 'authority', 'vintage' (e.g. 'COD2026-06'), and "
            "'access_date' (YYYY-MM-DD) fields before running against this admin dataset."
        )
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise AdminSourceManifestError(f"Could not read/parse admin-boundary manifest {manifest_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise AdminSourceManifestError(f"Admin-boundary manifest {manifest_path} must contain a JSON object.")

    authority = raw.get("authority")
    if not isinstance(authority, str) or not authority.strip():
        raise AdminSourceManifestError(f"Admin-boundary manifest {manifest_path} is missing a non-empty 'authority'.")

    vintage = raw.get("vintage")
    if not isinstance(vintage, str) or not _VINTAGE_PATTERN.match(vintage):
        raise AdminSourceManifestError(
            f"Admin-boundary manifest {manifest_path} has an invalid 'vintage' "
            f"(got {vintage!r}); expected format '<AUTHORITY><YYYY-MM>', e.g. 'COD2026-06'."
        )

    access_date = raw.get("access_date")
    if not isinstance(access_date, str):
        raise AdminSourceManifestError(f"Admin-boundary manifest {manifest_path} is missing 'access_date'.")
    try:
        date.fromisoformat(access_date)
    except ValueError as exc:
        raise AdminSourceManifestError(
            f"Admin-boundary manifest {manifest_path} has an invalid 'access_date' (got {access_date!r}): {exc}"
        ) from exc

    return {"authority": authority.strip(), "vintage": vintage, "access_date": access_date}


def resolve_worldpop_path(
    iso3: str,
    worldpop_path: str | Path | None = None,
    worldpop_dir: str | Path = DEFAULT_WORLDPOP_DIR,
) -> Path:
    """Resolve an explicit or previously downloaded country WorldPop raster."""

    if worldpop_path is not None:
        return _resolved(worldpop_path)
    iso3_norm = str(iso3).strip().lower()
    directory = _resolved(worldpop_dir)
    preferred = directory / f"{iso3_norm}_pop_2025_CN_100m_R2025A_v1.tif"
    if preferred.exists():
        return preferred
    candidates = sorted(
        {
            path
            for pattern in (f"{iso3_norm}_pop_*.tif", f"{iso3_norm}*.tif")
            for path in directory.glob(pattern)
            if path.is_file() and path.stat().st_size > 0
        },
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    return candidates[0] if candidates else preferred


def resolve_ibtracs_path(
    ibtracs_path: str | Path | None = None,
    ibtracs_dir: str | Path = DEFAULT_IBTRACS_DIR,
) -> Path:
    """Resolve an explicit or reusable local IBTrACS CSV export."""

    if ibtracs_path is not None:
        return _resolved(ibtracs_path)
    directory = _resolved(ibtracs_dir)
    preferred = directory / "ibtracs.csv"
    if preferred.exists():
        return preferred
    candidates = sorted(
        (
            path
            for path in directory.glob("*.csv")
            if path.is_file() and "ibtracs" in path.name.lower() and path.stat().st_size > 0
        ),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    return candidates[0] if candidates else preferred


def resolve_hydrorivers_path(hydrorivers_path: str | Path | None = None) -> Path:
    """Resolve the HydroRIVERS reach dataset used for river-corridor masking."""

    return _resolved(hydrorivers_path or DEFAULT_HYDRORIVERS_PATH)


def resolve_hydrolakes_path(hydrolakes_path: str | Path | None = None) -> Path:
    """Resolve the HydroLAKES dataset (reserved for future lake-drought handling)."""

    return _resolved(hydrolakes_path or DEFAULT_HYDROLAKES_PATH)


def shared_cache_root(output_root: str | Path, source: str) -> Path:
    """Return a cache shared across hazards, countries, and run windows."""

    path = _resolved(output_root) / "_cache" / "_shared" / source.strip().lower()
    path.mkdir(parents=True, exist_ok=True)
    return path


def url_cache_key(url: str, length: int = 20) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:length]


def checksum_path(path: str | Path, *, cache_dir: str | Path | None = None) -> str:
    """Hash a file or directory deterministically for input provenance.

    When `cache_dir` is given, the digest is cached on disk (`cache_dir/
    checksum_cache.json`) keyed by `(resolved path, size, mtime_ns)`, so a
    large, unchanged reference input (e.g. the ~988MB admin boundary archive
    cyclone/earthquake both checksum) is hashed once per distinct (path,
    size, mtime) rather than once per CLI invocation across an entire batch
    (PERF-004) -- each hazard run is its own subprocess, so this cache only
    helps because it is persisted to disk, not merely memoized in-process.
    Without `cache_dir` (the default), behavior is unchanged: always
    recompute, nothing written to disk.
    """

    source = _resolved(path)
    stat = source.stat()
    cache_key = f"{source}|{stat.st_size}|{stat.st_mtime_ns}"
    cache_file = Path(cache_dir) / "checksum_cache.json" if cache_dir is not None else None
    cached: dict[str, str] = {}
    if cache_file is not None and cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cached = {}
        if cache_key in cached:
            return cached[cache_key]

    digest = hashlib.sha256()
    paths = sorted(item for item in source.rglob("*") if item.is_file()) if source.is_dir() else [source]
    for item in paths:
        if source.is_dir():
            digest.update(str(item.relative_to(source)).encode("utf-8"))
        with item.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    result = digest.hexdigest()

    if cache_file is not None:
        cached[cache_key] = result
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cached), encoding="utf-8")
    return result


def link_cached_asset(cache_path: str | Path, run_path: str | Path) -> Path:
    """Hard-link a cached asset into a run, copying only across filesystems."""

    source = _resolved(cache_path)
    destination = Path(run_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        destination.unlink()
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)
    return destination
