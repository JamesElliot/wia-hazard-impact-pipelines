from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from wia_pipelines.hazards.earthquake.pipeline import RunInputs, validate_inputs


def _inputs(tmp_path: Path) -> RunInputs:
    admin = gpd.GeoDataFrame(
        {
            "ISO3": ["TST", "TST"],
            "ADM0_PCODE": ["TST", "TST"],
            "ADM1_PCODE": ["TST1", "TST1"],
            "ADM2_PCODE": ["TST101", "TST102"],
            "ADM2_EN": ["West", "East"],
            "ADM2_REF": ["West", "East"],
        },
        geometry=[box(-1, 0, 0, 1), box(0, 0, 1, 1)],
        crs=4326,
    )
    admin_path = tmp_path / "admin.gpkg"
    admin.to_file(admin_path, driver="GPKG")
    population_path = tmp_path / "population.tif"
    with rasterio.open(
        population_path,
        "w",
        driver="GTiff",
        height=10,
        width=20,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(-1, 1, 0.1, 0.1),
        nodata=-9999,
    ) as destination:
        destination.write(np.ones((10, 20), dtype="float32"), 1)
    return RunInputs(
        iso3="TST",
        window_end="2025-12-31",
        worldpop=population_path,
        admin=admin_path,
        out=tmp_path / "outputs",
    )


def test_validate_inputs_reports_admin_and_population(tmp_path):
    result = validate_inputs(_inputs(tmp_path))
    assert result["window_start"] == "2025-01-01"
    assert result["window_end"] == "2025-12-31"
    assert result["admin_features"] == 2
    assert result["population"]["width"] == 20
