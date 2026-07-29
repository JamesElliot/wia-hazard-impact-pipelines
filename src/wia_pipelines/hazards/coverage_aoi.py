from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.admin import build_admin_aoi, filter_admin_for_iso3, load_admin_layer


def prepare_country_admin_context(
    iso3: str,
    admin_path: Path,
    admin_layer: str = "admin2",
    iso3_field: str = "iso3",
    buffer_km: float = 0.0,
    cds_buffer_deg: float = 0.25,
) -> dict[str, Any]:
    admin_all = load_admin_layer(admin_path, layer=admin_layer)
    admin_country = filter_admin_for_iso3(admin_all, iso3=iso3, iso3_field=iso3_field)
    aoi = build_admin_aoi(admin_country, buffer_km=buffer_km, out_crs="EPSG:4326")
    west, south, east, north = aoi["admin_bounds"]
    west_b = max(-180.0, west - cds_buffer_deg)
    south_b = max(-90.0, south - cds_buffer_deg)
    east_b = min(180.0, east + cds_buffer_deg)
    north_b = min(90.0, north + cds_buffer_deg)
    return {
        "iso3": iso3.upper(),
        "admin_gdf": admin_country,
        "admin_bounds_wsen": (west, south, east, north),
        "cds_bounds_wsen": (west_b, south_b, east_b, north_b),
        "cds_area_nwse": [north_b, west_b, south_b, east_b],
        "cds_buffer_deg": cds_buffer_deg,
    }
