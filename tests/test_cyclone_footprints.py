import pandas as pd

from wia_pipelines.hazards.cyclone.footprints import build_wind_radii_footprint, quadrant_polygon


def test_quadrant_polygon_is_local_at_antimeridian():
    polygon = quadrant_polygon(179.9, 10, {q: 50 for q in ("NE", "SE", "SW", "NW")})
    assert polygon.is_valid
    assert polygon.bounds[2] - polygon.bounds[0] < 2


def test_track_interpolation_produces_one_valid_swath():
    rows = []
    for time, lon in (("2026-01-01", 0.0), ("2026-01-01 06:00", 1.0)):
        row = {"ISO_TIME": pd.Timestamp(time), "LON": lon, "LAT": 0.0}
        row.update({f"USA_R34_{q}": 40 for q in ("NE", "SE", "SW", "NW")})
        rows.append(row)
    result = build_wind_radii_footprint(pd.DataFrame(rows), 63, spacing_km=25)
    assert result.completeness == 1
    assert result.geometry.is_valid
    assert result.geometry.geom_type in {"Polygon", "MultiPolygon"}
