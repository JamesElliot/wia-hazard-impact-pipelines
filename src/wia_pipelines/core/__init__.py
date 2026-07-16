"""Core reusable building blocks for hazard pipelines."""

from .admin import (
    admin_bounds_hash,
    build_admin_aoi,
    filter_admin_for_iso3,
    load_admin_layer,
)
from .aggregation import labelled_sum, zonal_sum
from .assets import (
    DEFAULT_ADMIN_PATH,
    DEFAULT_IBTRACS_DIR,
    DEFAULT_WORLDPOP_DIR,
    checksum_path,
    link_cached_asset,
    resolve_admin_path,
    resolve_ibtracs_path,
    resolve_worldpop_path,
    shared_cache_root,
    url_cache_key,
)
from .cds import download_cds, ensure_downloads, extract_zip_to_dir, months_for_last_n
from .io_paths import (
    append_artifact,
    build_run_layout,
    create_run_dirs,
    ensure_dir,
    write_json,
)
from .pipeline import (
    HAZARD_METHODS,
    HazardMethod,
    build_hazard_run_context,
    hazard_method,
    record_artifact,
    standardize_admin_summary,
    sync_run_metadata,
)
from .raster_ops import align_to_reference, reproject_array_to_grid, write_array_geotiff
from .worldpop import worldpop_profile_and_bounds

__all__ = [
    "admin_bounds_hash",
    "DEFAULT_ADMIN_PATH",
    "DEFAULT_IBTRACS_DIR",
    "DEFAULT_WORLDPOP_DIR",
    "HAZARD_METHODS",
    "HazardMethod",
    "align_to_reference",
    "append_artifact",
    "build_admin_aoi",
    "build_hazard_run_context",
    "build_run_layout",
    "create_run_dirs",
    "checksum_path",
    "download_cds",
    "ensure_dir",
    "ensure_downloads",
    "extract_zip_to_dir",
    "filter_admin_for_iso3",
    "load_admin_layer",
    "link_cached_asset",
    "labelled_sum",
    "hazard_method",
    "months_for_last_n",
    "reproject_array_to_grid",
    "record_artifact",
    "resolve_admin_path",
    "resolve_ibtracs_path",
    "resolve_worldpop_path",
    "shared_cache_root",
    "standardize_admin_summary",
    "sync_run_metadata",
    "write_array_geotiff",
    "write_json",
    "url_cache_key",
    "worldpop_profile_and_bounds",
    "zonal_sum",
]
