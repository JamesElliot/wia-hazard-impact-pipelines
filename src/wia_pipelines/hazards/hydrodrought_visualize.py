from __future__ import annotations

from pathlib import Path
from typing import Mapping

import geopandas as gpd
import pandas as pd

from ..core.mapping import plot_admin_pct_affected, plot_hazard_footprint


def write_run_maps(
    admin: gpd.GeoDataFrame,
    table: pd.DataFrame,
    default_threshold_mask_tif: Path,
    output_dir: Path,
    *,
    iso3: str,
    pcode_column: str,
    admin_level: int,
    default_threshold_label: str,
    window_start: str,
    window_end: str,
) -> Mapping[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    footprint_map = output_dir / f"{iso3}_hydrodrought_affected_population_{window_end}.png"
    admin_map = output_dir / f"{iso3}_pct_affected_admin{admin_level}_{window_end}.png"

    plot_hazard_footprint(
        admin,
        default_threshold_mask_tif,
        footprint_map,
        iso3=iso3,
        hazard_label=f"hydrological drought exposure (SRI3 {default_threshold_label})",
        window_start=window_start,
        window_end=window_end,
        binary=True,
        color="#2166ac",
    )
    plot_admin_pct_affected(
        admin,
        table,
        admin_map,
        pcode_column=pcode_column,
        value_column="pct_affected",
        iso3=iso3,
        hazard_label="population affected by hydrological drought",
        admin_level=admin_level,
        window_start=window_start,
        window_end=window_end,
        cmap="PuBu",
    )
    return {"hydrodrought_affected_population": footprint_map, "admin_percent_affected": admin_map}
