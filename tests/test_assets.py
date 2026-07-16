from pathlib import Path

from wia_pipelines.core.assets import (
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
