from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ..core.io_paths import build_run_layout


@dataclass(frozen=True)
class FloodRecurrenceResult:
    raster_path: Path
    map_path: Path
    metadata_path: Path
    years: tuple[int, ...]
    pixel_counts: dict[int, int]


def discover_annual_flood_masks(
    output_root: str | Path,
    iso3: str,
    start_year: int,
    end_year: int,
) -> list[tuple[int, Path]]:
    """Find exactly one standard annual flood mask for every requested year."""

    root = Path(output_root).expanduser().resolve()
    country = str(iso3).strip().upper()
    found: list[tuple[int, Path]] = []
    for year in range(int(start_year), int(end_year) + 1):
        layout = build_run_layout(root, country, f"{year}-12-31_m12", "flood")
        path = layout["rasters"] / "flood" / f"{country}_flood_any_{year}-01-01_{year}-12-31.tif"
        if not path.is_file():
            raise FileNotFoundError(f"Annual flood mask not found for {country} {year}: {path}")
        found.append((year, path))
    return found


def _validate_matching_grids(datasets: Iterable[Any]) -> Any:
    sources = list(datasets)
    if not sources:
        raise ValueError("At least one annual flood mask is required.")
    reference = sources[0]
    for source in sources[1:]:
        if (
            source.shape != reference.shape
            or source.crs != reference.crs
            or not source.transform.almost_equals(reference.transform)
        ):
            raise ValueError("Annual flood masks must have identical shape, CRS, and transform.")
    return reference


def create_flood_recurrence_raster(
    annual_masks: list[Path],
    output_path: Path,
    *,
    country_geometry: Any | None = None,
) -> dict[int, int]:
    """Sum annual binary masks into a 0..N recurrence raster, block by block."""

    import numpy as np
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.features import geometry_mask
    from rasterio.windows import Window
    from shapely.geometry import mapping

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sources = [rasterio.open(path) for path in annual_masks]
    try:
        reference = _validate_matching_grids(sources)
        if len(sources) > 254:
            raise ValueError("At most 254 annual masks can be represented in a uint8 recurrence raster.")
        profile = reference.profile.copy()
        profile.update(
            count=1,
            dtype="uint8",
            nodata=255,
            compress="deflate",
            predictor=2,
            tiled=True,
            blockxsize=512,
            blockysize=512,
        )
        counts = np.zeros(len(sources) + 1, dtype="int64")
        with rasterio.open(output_path, "w", **profile) as destination:
            windows = (
                Window(
                    col_off,
                    row_off,
                    min(512, reference.width - col_off),
                    min(512, reference.height - row_off),
                )
                for row_off in range(0, reference.height, 512)
                for col_off in range(0, reference.width, 512)
            )
            for window in windows:
                recurrence = np.zeros((int(window.height), int(window.width)), dtype="uint8")
                for source in sources:
                    recurrence += (source.read(1, window=window) > 0).astype("uint8")
                if country_geometry is None:
                    inside = np.ones(recurrence.shape, dtype=bool)
                else:
                    inside = geometry_mask(
                        [mapping(country_geometry)],
                        out_shape=recurrence.shape,
                        transform=reference.window_transform(window),
                        invert=True,
                    )
                output = np.where(inside, recurrence, 255).astype("uint8")
                destination.write(output, 1, window=window)
                counts += np.bincount(recurrence[inside], minlength=len(sources) + 1)
            factors = [factor for factor in (2, 4, 8, 16, 32) if reference.width // factor >= 1]
            destination.build_overviews(factors, Resampling.nearest)
            destination.update_tags(
                recurrence_definition="Number of annual binary flood masks with value > 0",
                years_count=str(len(sources)),
            )
        return {value: int(count) for value, count in enumerate(counts)}
    finally:
        for source in sources:
            source.close()


def render_flood_recurrence_map(
    raster_path: Path,
    map_path: Path,
    *,
    country_boundaries: Any,
    rivers: Any,
    lakes: Any,
    iso3: str,
    years: tuple[int, ...],
    max_display_dimension: int = 2200,
) -> None:
    """Render a publication-ready discrete recurrence map from the output raster."""

    import matplotlib.pyplot as plt
    import numpy as np
    import rasterio
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    from rasterio.enums import Resampling

    with rasterio.open(raster_path) as source:
        scale = max(source.width, source.height) / float(max_display_dimension)
        out_height = max(1, round(source.height / max(1.0, scale)))
        out_width = max(1, round(source.width / max(1.0, scale)))
        data = source.read(
            1,
            out_shape=(out_height, out_width),
            resampling=Resampling.nearest,
            masked=True,
        )
        bounds = source.bounds
        raster_crs = source.crs

    boundaries = country_boundaries.to_crs(raster_crs)
    rivers = rivers.to_crs(raster_crs)
    lakes = lakes.to_crs(raster_crs)
    colors = ["#f3f1ea", "#d9f0d3", "#addd8e", "#78c679", "#31a354", "#006837"]
    cmap = ListedColormap(colors)
    cmap.set_bad((1, 1, 1, 0))
    norm = BoundaryNorm(np.arange(-0.5, len(years) + 1.5, 1), cmap.N)

    fig, ax = plt.subplots(figsize=(10.5, 8.2), constrained_layout=True)
    ax.imshow(
        data,
        cmap=cmap,
        norm=norm,
        extent=(bounds.left, bounds.right, bounds.bottom, bounds.top),
        interpolation="nearest",
        origin="upper",
    )
    if not lakes.empty:
        lakes.plot(ax=ax, facecolor="#9dd9ec", edgecolor="#2b8cbe", linewidth=0.35, alpha=0.9)
    if not rivers.empty:
        flow = np.maximum(rivers["DIS_AV_CMS"].fillna(0).to_numpy(dtype=float), 0.0)
        widths = np.clip(np.log10(flow + 1.0) * 0.42, 0.18, 1.5)
        rivers.plot(ax=ax, color="#2b8cbe", linewidth=widths, alpha=0.72)
    country_outline = boundaries.geometry.union_all()
    country_boundaries.__class__({"geometry": [country_outline]}, crs=boundaries.crs).boundary.plot(
        ax=ax, color="#111111", linewidth=1.15
    )
    ax.set_title(
        f"South Sudan: annual flood recurrence, {years[0]}–{years[-1]}",
        loc="left",
        fontsize=16,
        fontweight="bold",
        pad=12,
    )
    ax.text(
        0,
        1.005,
        f"Number of years flooded at least once in each pixel ({len(years)} annual windows)",
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=10,
        color="#444444",
    )
    handles = [
        Patch(facecolor=color, edgecolor="#777777", linewidth=0.25, label=str(value))
        for value, color in enumerate(colors)
    ]
    handles.extend(
        [
            Line2D([0], [0], color="#2b8cbe", linewidth=1.2, label="Rivers"),
            Patch(facecolor="#9dd9ec", edgecolor="#2b8cbe", linewidth=0.4, label="Lakes"),
        ]
    )
    ax.legend(
        handles=handles,
        title="Years flooded / hydrography",
        loc="lower left",
        ncol=4,
        frameon=True,
        framealpha=0.95,
        columnspacing=0.9,
        handlelength=1.4,
    )
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_aspect("equal")
    ax.grid(color="#888888", linewidth=0.3, alpha=0.25)
    ax.text(
        1,
        -0.075,
        "Sources: Copernicus GFM; HydroRIVERS v1.0; HydroLAKES v1.0",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=8,
        color="#555555",
    )
    map_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(map_path, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def build_flood_recurrence(
    *,
    output_root: str | Path,
    iso3: str,
    start_year: int,
    end_year: int,
    admin_path: str | Path,
    admin_layer: str = "admin2",
    iso3_field: str = "iso3",
    rivers_path: str | Path | None = None,
    lakes_path: str | Path | None = None,
    lakes_fallback_path: str | None = None,
    river_min_discharge_cms: float = 1.0,
) -> FloodRecurrenceResult:
    """Build the recurrence GeoTIFF, map PNG, and provenance JSON."""

    import geopandas as gpd

    root = Path(output_root).expanduser().resolve()
    country = str(iso3).strip().upper()
    annual = discover_annual_flood_masks(root, country, start_year, end_year)
    years = tuple(year for year, _ in annual)
    # Filter at the GDAL layer so malformed features belonging to unrelated
    # countries in a large global archive cannot break this country-level task.
    admin = gpd.read_file(
        Path(admin_path).expanduser().resolve(),
        layer=admin_layer,
        where=f"{iso3_field} LIKE '{country}'",
    )
    if admin.empty:
        raise ValueError(f"No {admin_layer} features found for {iso3_field}={country}.")
    admin_4326 = admin.to_crs("EPSG:4326")
    country_geometry = admin_4326.geometry.union_all()
    country_frame = gpd.GeoDataFrame({"geometry": [country_geometry]}, crs="EPSG:4326")
    country_bbox = tuple(float(value) for value in country_geometry.bounds)

    if rivers_path is None or lakes_path is None:
        raise ValueError("rivers_path and lakes_path are required to render hydrography.")
    rivers_source = str(Path(rivers_path).expanduser().resolve())
    rivers = gpd.read_file(
        rivers_source,
        layer="HydroRIVERS_v10",
        bbox=country_bbox,
        columns=["DIS_AV_CMS", "ORD_FLOW"],
    )
    rivers = rivers[rivers["DIS_AV_CMS"].fillna(0) >= float(river_min_discharge_cms)]
    rivers = gpd.clip(rivers, country_frame)

    lakes_source = str(Path(lakes_path).expanduser().resolve())
    try:
        lakes = gpd.read_file(
            lakes_source,
            layer="HydroLAKES_polys_v10",
            bbox=country_bbox,
            columns=["Hylak_id", "Lake_name", "Lake_type", "Lake_area"],
        )
    except Exception:
        if not lakes_fallback_path:
            raise
        lakes_source = lakes_fallback_path
        lakes = gpd.read_file(
            lakes_source,
            layer="HydroLAKES_polys_v10",
            bbox=country_bbox,
            columns=["Hylak_id", "Lake_name", "Lake_type", "Lake_area"],
        )
    lakes = gpd.clip(lakes, country_frame)
    destination = root / country / "recurrence"
    stem = f"{country}_flood_recurrence_{years[0]}_{years[-1]}"
    raster_path = destination / f"{stem}.tif"
    map_path = destination / f"{stem}.png"
    metadata_path = destination / f"{stem}.json"
    pixel_counts = create_flood_recurrence_raster(
        [path for _, path in annual],
        raster_path,
        country_geometry=country_geometry,
    )
    render_flood_recurrence_map(
        raster_path,
        map_path,
        country_boundaries=admin,
        rivers=rivers,
        lakes=lakes,
        iso3=country,
        years=years,
    )
    metadata = {
        "iso3": country,
        "years": list(years),
        "definition": "Count of annual 12-month windows in which each pixel flooded at least once",
        "annual_masks": [str(path) for _, path in annual],
        "recurrence_raster": str(raster_path),
        "map_png": str(map_path),
        "pixel_counts": {str(value): count for value, count in pixel_counts.items()},
        "hydrography": {
            "rivers_source": rivers_source,
            "rivers_count": int(len(rivers)),
            "river_min_discharge_cms": float(river_min_discharge_cms),
            "lakes_source": lakes_source,
            "lakes_count": int(len(lakes)),
        },
        "nodata": 255,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return FloodRecurrenceResult(raster_path, map_path, metadata_path, years, pixel_counts)
