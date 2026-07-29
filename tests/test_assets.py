import json
import time
from pathlib import Path

from wia_pipelines.core.assets import (
    checksum_path,
    link_cached_asset,
    resolve_ibtracs_path,
    resolve_worldpop_path,
    shared_cache_root,
)


def test_resolvers_reuse_existing_country_and_track_assets(tmp_path: Path):
    population_dir = tmp_path / "population"
    population_dir.mkdir()
    population = population_dir / "moz_pop_2024_CN_100m_legacy.tif"
    population.write_bytes(b"population")
    cyclone_dir = tmp_path / "cyclone"
    cyclone_dir.mkdir()
    tracks = cyclone_dir / "IBTrACS.last3years.v04r01.csv"
    tracks.write_text("SID,ISO_TIME\n", encoding="utf-8")

    assert resolve_worldpop_path("MOZ", worldpop_dir=population_dir) == population
    assert resolve_ibtracs_path(ibtracs_dir=cyclone_dir) == tracks


def test_shared_cache_can_materialize_asset_in_multiple_runs(tmp_path: Path):
    cached = shared_cache_root(tmp_path, "usgs") / "asset.bin"
    cached.write_bytes(b"shared")
    first = link_cached_asset(cached, tmp_path / "run-a" / "raw" / "asset.bin")
    second = link_cached_asset(cached, tmp_path / "run-b" / "raw" / "asset.bin")

    assert first.read_bytes() == b"shared"
    assert second.read_bytes() == b"shared"


def test_checksum_path_without_cache_dir_writes_nothing(tmp_path: Path):
    target = tmp_path / "admin.zip"
    target.write_bytes(b"admin-boundary-bytes")
    digest = checksum_path(target)
    assert digest == checksum_path(target)
    assert not (tmp_path / "checksum_cache.json").exists()


def test_checksum_path_persists_to_disk_across_calls(tmp_path: Path):
    target = tmp_path / "admin.zip"
    target.write_bytes(b"admin-boundary-bytes")
    cache_dir = tmp_path / "_cache"

    first = checksum_path(target, cache_dir=cache_dir)
    cache_file = cache_dir / "checksum_cache.json"
    assert cache_file.exists()
    stored = json.loads(cache_file.read_text(encoding="utf-8"))
    assert first in stored.values()

    # A fresh call (simulating a new subprocess in a batch, PERF-004) reads the
    # same on-disk cache rather than needing an in-process memo.
    second = checksum_path(target, cache_dir=cache_dir)
    assert second == first


def test_checksum_path_cache_hit_returns_cached_value_without_recomputing(tmp_path: Path):
    target = tmp_path / "admin.zip"
    target.write_bytes(b"admin-boundary-bytes")
    cache_dir = tmp_path / "_cache"
    real = checksum_path(target, cache_dir=cache_dir)

    cache_file = cache_dir / "checksum_cache.json"
    stored = json.loads(cache_file.read_text(encoding="utf-8"))
    (key,) = stored.keys()
    stored[key] = "deadbeef" * 8
    cache_file.write_text(json.dumps(stored), encoding="utf-8")

    assert checksum_path(target, cache_dir=cache_dir) == "deadbeef" * 8
    assert real != "deadbeef" * 8


def test_checksum_path_cache_invalidates_on_content_and_mtime_change(tmp_path: Path):
    target = tmp_path / "admin.zip"
    target.write_bytes(b"admin-boundary-bytes")
    cache_dir = tmp_path / "_cache"
    original = checksum_path(target, cache_dir=cache_dir)

    time.sleep(0.01)
    target.write_bytes(b"different-content-different-size")
    updated = checksum_path(target, cache_dir=cache_dir)
    assert updated != original

    stored = json.loads((cache_dir / "checksum_cache.json").read_text(encoding="utf-8"))
    assert len(stored) == 2  # both (path, old size/mtime) and (path, new size/mtime) keys retained
