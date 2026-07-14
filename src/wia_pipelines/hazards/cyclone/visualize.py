from __future__ import annotations

# Matplotlib must be configured after redirecting its writable cache directories.
# ruff: noqa: E402

import os
from pathlib import Path
import tempfile
from typing import Mapping

import geopandas as gpd

_CACHE_ROOT = Path(tempfile.gettempdir()) / "wia-hi06-cache"
os.environ.setdefault("MPLCONFIGDIR", str(_CACHE_ROOT / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(_CACHE_ROOT))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling


def _map_extent(admin: gpd.GeoDataFrame, padding_fraction: float = 0.04) -> tuple[float, ...]:
    xmin, ymin, xmax, ymax = admin.to_crs(4326).total_bounds
    xpad = max((xmax - xmin) * padding_fraction, 0.1)
    ypad = max((ymax - ymin) * padding_fraction, 0.1)
    return xmin - xpad, xmax + xpad, ymin - ypad, ymax + ypad


def _style_map(ax: plt.Axes, extent: tuple[float, ...]) -> None:
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(color="#d8d8d8", linewidth=0.45, alpha=0.6)
    ax.set_axisbelow(True)


def plot_tracks_and_affected_population(
    admin: gpd.GeoDataFrame,
    tracks: pd.DataFrame,
    population_path: Path,
    mask_path: Path,
    primary_threshold: int,
    output_path: Path,
    *,
    iso3: str,
    window_start: str,
    window_end: str,
    max_plot_dimension: int = 1800,
) -> None:
    """Plot candidate storm tracks over populated cells inside the primary wind mask."""
    admin_4326 = admin.to_crs(4326)
    with rasterio.open(population_path) as population, rasterio.open(mask_path) as mask:
        if population.crs != mask.crs or population.transform != mask.transform:
            raise ValueError("Population and wind mask grids must match for map generation")
        scale = min(1.0, max_plot_dimension / max(population.width, population.height))
        out_height = max(1, round(population.height * scale))
        out_width = max(1, round(population.width * scale))
        population_sample = population.read(
            1,
            out_shape=(out_height, out_width),
            masked=True,
            out_dtype="float32",
            resampling=Resampling.average,
        )
        primary_band = next(
            (
                index
                for index in range(1, mask.count + 1)
                if mask.descriptions[index - 1] == f"wind_ge_{primary_threshold}_kmh"
            ),
            None,
        )
        if primary_band is None:
            raise ValueError(f"Wind mask has no {primary_threshold} km/h band")
        wind_sample = mask.read(
            primary_band,
            out_shape=(out_height, out_width),
            out_dtype="float32",
            resampling=Resampling.average,
        )
        affected = (
            (wind_sample > 0)
            & (~np.ma.getmaskarray(population_sample))
            & (np.asarray(population_sample.filled(0)) > 0)
        )
        raster_extent = (mask.bounds.left, mask.bounds.right, mask.bounds.bottom, mask.bounds.top)

    fig, ax = plt.subplots(figsize=(9, 10), constrained_layout=True)
    affected_layer = np.ma.masked_where(~affected, affected.astype(np.uint8))
    ax.imshow(
        affected_layer,
        extent=raster_extent,
        origin="upper",
        interpolation="nearest",
        cmap=ListedColormap(["#e85d04"]),
        alpha=0.58,
        zorder=1,
    )
    admin_4326.boundary.plot(ax=ax, color="#777777", linewidth=0.35, alpha=0.7, zorder=2)
    admin_4326.dissolve().boundary.plot(ax=ax, color="#222222", linewidth=0.9, zorder=3)

    track_handles: list[Line2D] = []
    colors = plt.get_cmap("tab10")
    for index, (sid, storm) in enumerate(tracks.groupby("SID", sort=True)):
        storm = storm.sort_values("ISO_TIME")
        color = colors(index % 10)
        ax.plot(storm["LON"], storm["LAT"], color=color, linewidth=1.5, zorder=4)
        ax.scatter(storm["LON"], storm["LAT"], color=color, s=5, zorder=5)
        names = storm["NAME"].dropna().astype(str) if "NAME" in storm else pd.Series(dtype=str)
        name = names.iloc[0] if not names.empty else str(sid)
        track_handles.append(Line2D([0], [0], color=color, linewidth=1.8, label=f"{name} ({sid})"))

    handles: list[object] = [Patch(facecolor="#e85d04", alpha=0.58, label="Affected population mask")]
    handles.extend(track_handles)
    ax.legend(handles=handles, loc="lower left", frameon=True, fontsize=8)
    _style_map(ax, _map_extent(admin_4326))
    ax.set_title(
        f"{iso3}: storm tracks and population within ≥{primary_threshold} km/h wind footprints\n"
        f"{window_start} to {window_end}"
    )
    fig.savefig(output_path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_admin_percent_affected(
    admin: gpd.GeoDataFrame,
    results: pd.DataFrame,
    output_path: Path,
    *,
    iso3: str,
    admin_level: int,
    window_start: str,
    window_end: str,
) -> None:
    """Plot the percentage of population affected for the analysis admin units."""
    if len(admin) != len(results):
        raise ValueError("Admin features and result rows must align for map generation")
    mapped = admin.to_crs(4326).reset_index(drop=True).copy()
    mapped["pct_affected"] = pd.to_numeric(results["pct_affected"], errors="coerce").to_numpy()

    fig, ax = plt.subplots(figsize=(9, 10), constrained_layout=True)
    mapped.plot(
        ax=ax,
        column="pct_affected",
        cmap="YlOrRd",
        vmin=0,
        vmax=100,
        linewidth=0.35,
        edgecolor="#666666",
        missing_kwds={"color": "#d9d9d9", "label": "No population denominator"},
        legend=True,
        legend_kwds={"label": "Population affected (%)", "shrink": 0.72},
    )
    mapped.dissolve().boundary.plot(ax=ax, color="#222222", linewidth=0.9, zorder=3)
    _style_map(ax, _map_extent(mapped))
    ax.set_title(
        f"{iso3}: population affected by tropical-cyclone winds, admin {admin_level}\n"
        f"{window_start} to {window_end}"
    )
    fig.savefig(output_path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def write_run_maps(
    admin: gpd.GeoDataFrame,
    tracks: pd.DataFrame,
    results: pd.DataFrame,
    population_path: Path,
    mask_path: Path,
    output_dir: Path,
    *,
    iso3: str,
    end_label: str,
    window_start: str,
    primary_threshold: int,
    admin_level: int,
) -> Mapping[str, Path]:
    track_map = output_dir / f"HI06_{iso3}_tracks_affected_population_{end_label}.png"
    admin_map = output_dir / f"HI06_{iso3}_pct_affected_admin{admin_level}_{end_label}.png"
    plot_tracks_and_affected_population(
        admin,
        tracks,
        population_path,
        mask_path,
        primary_threshold,
        track_map,
        iso3=iso3,
        window_start=window_start,
        window_end=end_label,
    )
    plot_admin_percent_affected(
        admin,
        results,
        admin_map,
        iso3=iso3,
        admin_level=admin_level,
        window_start=window_start,
        window_end=end_label,
    )
    return {"tracks_affected_population": track_map, "admin_percent_affected": admin_map}
