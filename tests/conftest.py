"""Shared synthetic-fixture factories for hazard pipeline tests.

Centralizes the admin-GeoDataFrame + WorldPop-raster construction that was
previously duplicated (in places byte-for-byte) across
test_hazard_spei.py, test_hazard_hydrodrought.py, test_hazard_violence.py,
test_cyclone_pipeline.py, and test_earthquake_pipeline.py.

These are plain helper functions, not `@pytest.fixture`s -- the repo mixes
unittest.TestCase-style tests (which can't receive pytest fixture
injection) with plain pytest function tests, so a directly-importable
function is the one form both styles can use.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def make_worldpop_tif(
    path: Path,
    *,
    shape: tuple[int, int] = (4, 4),
    value: float = 1.0,
    nodata: float = -9999.0,
    transform: Any = None,
    dtype: str = "float32",
) -> Path:
    """Write a small synthetic WorldPop-style GeoTIFF (EPSG:4326) and return its path."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    height, width = shape
    if transform is None:
        transform = from_origin(0, height, 1, 1)
    data = np.full((height, width), value, dtype=dtype)
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": dtype,
        "crs": "EPSG:4326",
        "transform": transform,
        "nodata": nodata,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)
    return path


def make_admin_gpkg(
    path: Path,
    *,
    iso3: str = "AAA",
    n_features: int = 2,
    geometries: list | None = None,
    extra_columns: dict[str, list] | None = None,
    layer: str | None = None,
) -> Path:
    """Write a small synthetic admin-boundary GeoPackage (EPSG:4326) and return its path.

    The only unconditional column is ``iso3`` -- pass ``extra_columns`` for
    anything else a hazard's admin schema needs (e.g. ``adm_level`` for
    spei/hydrodrought, ``adm2_pcode`` for violence; a key in
    ``extra_columns`` overrides the default ``iso3`` values too if
    provided). Build the GeoDataFrame directly for schemas that diverge
    further (e.g. cyclone/earthquake's uppercase multi-level ADM*_PCODE
    fields), where this factory would need more parameters than it saves.
    """
    import geopandas as gpd
    from shapely.geometry import box

    if geometries is None:
        geometries = [box(i, 0, i + 1, 1) for i in range(n_features)]
    columns: dict[str, list] = {"iso3": [iso3] * len(geometries)}
    if extra_columns:
        columns.update(extra_columns)
    gdf = gpd.GeoDataFrame({**columns, "geometry": geometries}, crs="EPSG:4326")
    kwargs: dict[str, Any] = {"driver": "GPKG"}
    if layer:
        kwargs["layer"] = layer
    gdf.to_file(path, **kwargs)
    return path
