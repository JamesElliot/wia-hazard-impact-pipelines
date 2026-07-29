from __future__ import annotations

# Matplotlib must be configured after redirecting its writable cache directories.
# ruff: noqa: E402

import os
from pathlib import Path
import tempfile

_CACHE_ROOT = Path(tempfile.gettempdir()) / "wia-hazard-maps-cache"
os.environ.setdefault("MPLCONFIGDIR", str(_CACHE_ROOT / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(_CACHE_ROOT))

import matplotlib

matplotlib.use("Agg")

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from matplotlib.colors import ListedColormap
from rasterio.enums import Resampling


def map_extent(admin: gpd.GeoDataFrame, padding_fraction: float = 0.04) -> tuple[float, ...]:
    """Compute a padded (xmin, xmax, ymin, ymax) map extent from an admin GeoDataFrame in EPSG:4326."""
    xmin, ymin, xmax, ymax = admin.to_crs(4326).total_bounds
    xpad = max((xmax - xmin) * padding_fraction, 0.1)
    ypad = max((ymax - ymin) * padding_fraction, 0.1)
    return xmin - xpad, xmax + xpad, ymin - ypad, ymax + ypad


def style_map(ax: plt.Axes, extent: tuple[float, ...]) -> None:
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(color="#d8d8d8", linewidth=0.45, alpha=0.6)
    ax.set_axisbelow(True)


def plot_admin_pct_affected(
    admin: gpd.GeoDataFrame,
    table: pd.DataFrame,
    output_path: Path,
    *,
    pcode_column: str,
    value_column: str,
    iso3: str,
    hazard_label: str,
    admin_level: int,
    window_start: str,
    window_end: str,
    value_label: str = "Population affected (%)",
    vmin: float = 0.0,
    vmax: float = 100.0,
    cmap: str = "YlOrRd",
) -> Path:
    """Admin-level choropleth of an affected-population indicator, joined by admin pcode.

    Uses a key-based merge (not positional alignment) so it stays correct even
    when the result table has dropped or reordered rows relative to `admin`.
    """
    boundary = admin.to_crs(4326)
    mapped = boundary.merge(
        table[[pcode_column, value_column]], left_on=pcode_column, right_on=pcode_column, how="left"
    )

    fig, ax = plt.subplots(figsize=(9, 10), constrained_layout=True)
    mapped.plot(
        ax=ax,
        column=value_column,
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        linewidth=0.35,
        edgecolor="#666666",
        missing_kwds={"color": "#d9d9d9", "label": "No population denominator"},
        legend=True,
        legend_kwds={"label": value_label, "shrink": 0.72},
    )
    mapped.dissolve().boundary.plot(ax=ax, color="#222222", linewidth=0.9, zorder=3)
    style_map(ax, map_extent(mapped))
    ax.set_title(f"{iso3}: {hazard_label}, admin {admin_level}\n{window_start} to {window_end}")
    fig.savefig(output_path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path


def plot_hazard_footprint(
    admin: gpd.GeoDataFrame,
    raster_path: Path,
    output_path: Path,
    *,
    iso3: str,
    hazard_label: str,
    window_start: str,
    window_end: str,
    band: int = 1,
    binary: bool = True,
    cmap: str = "YlOrRd",
    color: str = "#e85d04",
    value_label: str = "Hazard intensity",
    max_plot_dimension: int = 1800,
) -> Path:
    """Footprint/extent map: a hazard raster (mask or intensity) overlaid on admin boundaries.

    If `binary` is True, `raster_path` is treated as a >0 mask and drawn as a
    single flat color (matching the cyclone/flood/utci/spei/violence binary
    mask convention). If False, positive values are colored by `cmap` — use
    this when a natural severity/intensity value is already available (flood
    days, event counts, threshold tiers) instead of a flat mask.
    """
    admin_4326 = admin.to_crs(4326)
    with rasterio.open(raster_path) as source:
        scale = min(1.0, max_plot_dimension / max(source.width, source.height))
        out_height = max(1, round(source.height * scale))
        out_width = max(1, round(source.width * scale))
        sample = source.read(
            band,
            out_shape=(out_height, out_width),
            masked=True,
            out_dtype="float32",
            resampling=Resampling.average,
        )
        raster_extent = (source.bounds.left, source.bounds.right, source.bounds.bottom, source.bounds.top)

    values = np.asarray(sample.filled(0), dtype="float32")
    positive = np.ma.masked_where(~(values > 0), values)

    fig, ax = plt.subplots(figsize=(9, 10), constrained_layout=True)
    if binary:
        ax.imshow(
            np.ma.masked_where(positive.mask, np.ones_like(values, dtype="uint8")),
            extent=raster_extent,
            origin="upper",
            interpolation="nearest",
            cmap=ListedColormap([color]),
            alpha=0.58,
            zorder=1,
        )
    else:
        image = ax.imshow(
            positive,
            extent=raster_extent,
            origin="upper",
            interpolation="nearest",
            cmap=cmap,
            alpha=0.75,
            zorder=1,
        )
        fig.colorbar(image, ax=ax, orientation="vertical", fraction=0.035, pad=0.02, label=value_label)
    admin_4326.boundary.plot(ax=ax, color="#777777", linewidth=0.35, alpha=0.7, zorder=2)
    admin_4326.dissolve().boundary.plot(ax=ax, color="#222222", linewidth=0.9, zorder=3)
    style_map(ax, map_extent(admin_4326))
    ax.set_title(f"{iso3}: {hazard_label}\n{window_start} to {window_end}")
    fig.savefig(output_path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path
