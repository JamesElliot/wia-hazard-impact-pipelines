import json
import time
from pathlib import Path

import pytest

from wia_pipelines.core.assets import (
    AdminSourceManifestError,
    admin_source_manifest_path,
    checksum_path,
    find_admin_path_for_iso3,
    link_cached_asset,
    load_admin_source_manifest,
    resolve_admin_path,
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


def test_admin_source_manifest_path_is_sibling_to_admin_dataset(tmp_path: Path):
    admin_path = tmp_path / "cod-ab" / "admin.gdb.zip"
    assert admin_source_manifest_path(admin_path) == tmp_path / "cod-ab" / "admin_source.json"


def test_load_admin_source_manifest_missing_raises(tmp_path: Path):
    admin_path = tmp_path / "admin.gdb.zip"
    admin_path.write_bytes(b"placeholder")
    with pytest.raises(AdminSourceManifestError):
        load_admin_source_manifest(admin_path)


def test_load_admin_source_manifest_malformed_json_raises(tmp_path: Path):
    admin_path = tmp_path / "admin.gdb.zip"
    admin_path.write_bytes(b"placeholder")
    admin_source_manifest_path(admin_path).write_text("not json", encoding="utf-8")
    with pytest.raises(AdminSourceManifestError):
        load_admin_source_manifest(admin_path)


def test_load_admin_source_manifest_bad_vintage_raises(tmp_path: Path):
    admin_path = tmp_path / "admin.gdb.zip"
    admin_path.write_bytes(b"placeholder")
    admin_source_manifest_path(admin_path).write_text(
        json.dumps({"authority": "COD", "vintage": "not-a-vintage", "access_date": "2026-06-14"}),
        encoding="utf-8",
    )
    with pytest.raises(AdminSourceManifestError):
        load_admin_source_manifest(admin_path)


def test_load_admin_source_manifest_bad_access_date_raises(tmp_path: Path):
    admin_path = tmp_path / "admin.gdb.zip"
    admin_path.write_bytes(b"placeholder")
    admin_source_manifest_path(admin_path).write_text(
        json.dumps({"authority": "COD", "vintage": "COD2026-06", "access_date": "not-a-date"}),
        encoding="utf-8",
    )
    with pytest.raises(AdminSourceManifestError):
        load_admin_source_manifest(admin_path)


def test_load_admin_source_manifest_valid_returns_fields(tmp_path: Path):
    admin_path = tmp_path / "admin.gdb.zip"
    admin_path.write_bytes(b"placeholder")
    admin_source_manifest_path(admin_path).write_text(
        json.dumps({"authority": "COD", "vintage": "COD2026-06", "access_date": "2026-06-14"}),
        encoding="utf-8",
    )
    manifest = load_admin_source_manifest(admin_path)
    assert manifest == {"authority": "COD", "vintage": "COD2026-06", "access_date": "2026-06-14"}



def test_find_admin_path_for_iso3_matches_registered_country(tmp_path: Path):
    registry = tmp_path / "cod-ab"
    override_dir = registry / "mli_sdn_moz_lbn"
    override_dir.mkdir(parents=True)
    (override_dir / "admin_boundaries.gpkg").write_bytes(b"placeholder")
    (override_dir / "admin_source.json").write_text(
        json.dumps(
            {
                "authority": "COD",
                "vintage": "COD2026-07",
                "access_date": "2026-07-29",
                "countries": {"MLI": {}, "SDN": {}},
            }
        ),
        encoding="utf-8",
    )

    assert find_admin_path_for_iso3("MLI", registry_dir=registry) == override_dir / "admin_boundaries.gpkg"
    assert find_admin_path_for_iso3("mli", registry_dir=registry) == override_dir / "admin_boundaries.gpkg"
    assert find_admin_path_for_iso3("AFG", registry_dir=registry) is None


def test_find_admin_path_for_iso3_ignores_dataset_missing_from_disk(tmp_path: Path):
    registry = tmp_path / "cod-ab"
    override_dir = registry / "mli_sdn_moz_lbn"
    override_dir.mkdir(parents=True)
    (override_dir / "admin_source.json").write_text(
        json.dumps({"authority": "COD", "vintage": "COD2026-07", "access_date": "2026-07-29", "countries": {"MLI": {}}}),
        encoding="utf-8",
    )
    # admin_boundaries.gpkg deliberately not created.
    assert find_admin_path_for_iso3("MLI", registry_dir=registry) is None


def test_resolve_admin_path_explicit_path_wins_over_iso3_override(tmp_path: Path):
    registry = tmp_path / "cod-ab"
    override_dir = registry / "mli_sdn_moz_lbn"
    override_dir.mkdir(parents=True)
    (override_dir / "admin_boundaries.gpkg").write_bytes(b"placeholder")
    (override_dir / "admin_source.json").write_text(
        json.dumps({"authority": "COD", "vintage": "COD2026-07", "access_date": "2026-07-29", "countries": {"MLI": {}}}),
        encoding="utf-8",
    )
    explicit = tmp_path / "explicit.gdb.zip"
    resolved = resolve_admin_path(explicit, iso3="MLI", registry_dir=registry)
    assert resolved == explicit.expanduser().resolve()


def test_resolve_admin_path_falls_back_to_default_without_override(tmp_path: Path):
    registry = tmp_path / "cod-ab"
    registry.mkdir()
    resolved = resolve_admin_path(None, iso3="AFG", registry_dir=registry)
    assert resolved.name == "global_admin_boundaries_matched_latest.gdb.zip"
