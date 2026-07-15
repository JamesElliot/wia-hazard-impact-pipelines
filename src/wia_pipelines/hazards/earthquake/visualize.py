from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from matplotlib.colors import BoundaryNorm
from matplotlib.patches import Patch
from rasterio.mask import mask
from rasterio.plot import plotting_extent


def write_run_maps(
    admin: gpd.GeoDataFrame,
    table: pd.DataFrame,
    maximum_mmi_path: Path,
    output_dir: Path,
    *,
    iso3: str,
    end_label: str,
    admin_level: int,
    primary_threshold: float,
    national_pct: float | None,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    boundary = admin.to_crs(4326)
    country = boundary.geometry.union_all()
    west, south, east, north = boundary.total_bounds

    severity_path = output_dir / f"HIEQ_{iso3}_maximum_mmi_{end_label}.png"
    with rasterio.open(maximum_mmi_path) as source:
        values, transform = mask(source, [country.__geo_interface__], crop=True, filled=False)
    fig, ax = plt.subplots(figsize=(8, 11), dpi=160)
    levels = [4.5, 5, 6, 7, 8, 9, 10]
    image = ax.imshow(
        np.ma.masked_invalid(values[0]),
        extent=plotting_extent(values[0], transform),
        origin="upper",
        cmap=plt.get_cmap("magma", len(levels) - 1),
        norm=BoundaryNorm(levels, len(levels) - 1),
    )
    boundary.boundary.plot(ax=ax, color="white", linewidth=0.35, alpha=0.8)
    ax.set(xlim=(west, east), ylim=(south, north), title=f"{iso3}: maximum earthquake MMI")
    ax.set_axis_off()
    fig.colorbar(image, ax=ax, orientation="horizontal", fraction=0.035, pad=0.02).set_label(
        f"Maximum MMI (primary threshold {primary_threshold:g})"
    )
    fig.savefig(severity_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    deprivation_path = output_dir / f"HIEQ_{iso3}_deprived_admin{admin_level}_{end_label}.png"
    key = f"adm{admin_level}_pcode"
    mapped = boundary.merge(table[[key, "deprivation"]], left_on=key, right_on=key, how="left")
    fig, ax = plt.subplots(figsize=(8, 11), dpi=160)
    mapped.plot(
        ax=ax,
        color=mapped["deprivation"].map({True: "#c23b53", False: "#d9dde3"}),
        edgecolor="white",
        linewidth=0.45,
    )
    mapped.boundary.plot(ax=ax, color="#202020", linewidth=0.4)
    label = "NA" if national_pct is None else f"{national_pct:.2f}%"
    ax.set(xlim=(west, east), ylim=(south, north), title=f"{iso3}: earthquake-deprived Admin-{admin_level}")
    ax.set_axis_off()
    ax.legend(
        handles=[
            Patch(facecolor="#c23b53", label=f"Deprived (> national {label})"),
            Patch(facecolor="#d9dde3", label="Not deprived"),
        ],
        loc="lower left",
    )
    fig.savefig(deprivation_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return {"maximum_mmi_map": severity_path, "deprivation_map": deprivation_path}
