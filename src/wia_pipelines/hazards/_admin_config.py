"""Shared admin-loading helpers for the cyclone and earthquake hazards.

These two hazards use a YAML-configured admin schema (arbitrary/case-varying
column names resolved via ``fields``) rather than the fixed `iso3`/pcode
convention `core/admin.load_admin_layer` assumes, so they don't fold into
that canonical loader (see ARCH-004's corrected scope). Their two
``_load_admin`` implementations were otherwise near-duplicates of each other
(ARCH-018) -- this module is the single shared implementation.

``fields`` is mutated in place to hold the actual (case-resolved) column
names: callers on both sides keep reading ``config["admin"]["fields"]`` after
the load and expect it to reflect the resolved names.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd


def actual_column(columns, configured: str | None) -> str | None:
    if not configured:
        return None
    if configured in columns:
        return configured
    by_lower = {str(column).lower(): str(column) for column in columns}
    return by_lower.get(str(configured).lower())


def load_yaml_hazard_admin(path: Path, iso3: str, admin_config: dict[str, Any]) -> gpd.GeoDataFrame:
    """Load, ISO3-filter, and validate an admin layer for the cyclone/earthquake
    YAML-config pattern. Raises immediately with a field-specific message when
    the ISO3 filter yields no features (cyclone's original behavior -- the more
    informative of the two hazards' prior implementations; earthquake's
    equivalent deferred check produced the same exception, just with a less
    specific message, so adopting this one changes no pass/fail outcome)."""
    fields = admin_config["fields"]
    level = int(admin_config["level"])
    read_kwargs = {"layer": admin_config["layer"]} if admin_config.get("layer") else {}
    try:
        admin = gpd.read_file(path, **read_kwargs)
    except Exception:
        if not read_kwargs:
            raise
        admin = gpd.read_file(path)
    if admin.empty or admin.crs is None:
        raise ValueError("Admin input must contain features and a declared CRS")
    for key, configured in list(fields.items()):
        actual = actual_column(admin.columns, configured)
        if actual is not None:
            fields[key] = actual
    iso_field = fields.get("iso3")
    if iso_field in admin.columns:
        subset = admin.loc[admin[iso_field].astype(str).str.upper() == iso3.upper()].copy()
        if subset.empty:
            raise ValueError(f"No admin features match ISO3 {iso3} in field {iso_field}")
        admin = subset
    elif fields.get("adm0_pcode") in admin.columns:
        column = fields["adm0_pcode"]
        subset = admin.loc[admin[column].astype(str).str[:3].str.upper() == iso3.upper()].copy()
        if subset.empty:
            raise ValueError(f"No admin features match ISO3 {iso3} by {column} prefix")
        admin = subset
    pcode = fields.get(f"adm{level}_pcode")
    if not pcode or pcode not in admin.columns:
        raise ValueError(f"Admin input is missing configured admin-{level} key: {pcode}")
    if admin[pcode].isna().any() or admin[pcode].duplicated().any():
        raise ValueError(f"Admin-{level} P-codes must be present and unique")
    admin = admin.loc[admin.geometry.notna() & ~admin.geometry.is_empty].copy()
    admin.geometry = admin.geometry.make_valid()
    return admin.reset_index(drop=True)
