from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path


DEFAULT_ADMIN_PATH = Path("./data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip")
DEFAULT_WORLDPOP_DIR = Path("./data/population")
DEFAULT_IBTRACS_DIR = Path("./data/cyclone")
DEFAULT_HYDRORIVERS_PATH = Path("./data/HydroRIVERS_v10/HydroRIVERS_v10.gdb")
DEFAULT_HYDROLAKES_PATH = Path("./data/HydroLAKES_polys_v10/HydroLAKES_polys_v10.gdb")


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def resolve_admin_path(admin_path: str | Path | None = None) -> Path:
    """Resolve the common administrative-boundary asset without requiring it at parse time."""

    return _resolved(admin_path or DEFAULT_ADMIN_PATH)


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
