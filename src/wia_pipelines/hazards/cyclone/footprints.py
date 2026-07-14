from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd
from pyproj import Geod
from shapely.geometry import Polygon
from shapely.ops import unary_union

from .tracks import QUADRANTS, radii_for_row


GEOD = Geod(ellps="WGS84")


@dataclass(frozen=True)
class FootprintResult:
    geometry: object | None
    observations_used: int
    observations_total: int
    agencies: tuple[str, ...]

    @property
    def completeness(self) -> float:
        return self.observations_used / self.observations_total if self.observations_total else 0.0


def _unwrap(lon: float, reference: float) -> float:
    return reference + ((lon - reference + 180) % 360) - 180


def quadrant_polygon(lon: float, lat: float, radii_km: dict[str, float], angular_step: int = 5) -> Polygon:
    vertices = []
    ranges = {"NE": (0, 90), "SE": (90, 180), "SW": (180, 270), "NW": (270, 360)}
    for quadrant in QUADRANTS:
        start, end = ranges[quadrant]
        for azimuth in range(start, end, angular_step):
            out_lon, out_lat, _ = GEOD.fwd(lon, lat, azimuth, radii_km[quadrant] * 1000)
            vertices.append((_unwrap(out_lon, lon), out_lat))
    out_lon, out_lat, _ = GEOD.fwd(lon, lat, 360, radii_km["NW"] * 1000)
    vertices.append((_unwrap(out_lon, lon), out_lat))
    polygon = Polygon(vertices)
    return polygon if polygon.is_valid else polygon.buffer(0)


def _intermediate_observations(
    first: tuple[float, float, dict[str, float]],
    second: tuple[float, float, dict[str, float]],
    spacing_km: float,
) -> list[tuple[float, float, dict[str, float]]]:
    lon1, lat1, radii1 = first
    lon2, lat2, radii2 = second
    _, _, distance_m = GEOD.inv(lon1, lat1, lon2, lat2)
    min_radius = min([*radii1.values(), *radii2.values()])
    effective_spacing = max(1.0, min(spacing_km, min_radius))
    steps = max(1, math.ceil(distance_m / 1000 / effective_spacing))
    if steps == 1:
        return []
    points = GEOD.npts(lon1, lat1, lon2, lat2, steps - 1)
    result = []
    for index, (lon, lat) in enumerate(points, start=1):
        fraction = index / steps
        radii = {q: radii1[q] + fraction * (radii2[q] - radii1[q]) for q in QUADRANTS}
        result.append((lon, lat, radii))
    return result


def build_wind_radii_footprint(
    storm: pd.DataFrame,
    threshold_kmh: int,
    spacing_km: float = 25,
    angular_step: int = 5,
    maximum_gap_hours: float = 12,
) -> FootprintResult:
    observations: list[tuple[pd.Timestamp, float, float, dict[str, float]]] = []
    agencies = []
    for _, row in storm.sort_values("ISO_TIME").iterrows():
        resolved = radii_for_row(row, threshold_kmh)
        if resolved is None:
            continue
        radii, agency = resolved
        observations.append((pd.Timestamp(row["ISO_TIME"]), float(row["LON"]), float(row["LAT"]), radii))
        agencies.append(agency)
    if not observations:
        return FootprintResult(None, 0, len(storm), ())

    sampled = []
    for index, observation in enumerate(observations):
        timestamp, lon, lat, radii = observation
        sampled.append((lon, lat, radii))
        if index + 1 < len(observations):
            next_time, next_lon, next_lat, next_radii = observations[index + 1]
            gap_hours = (next_time - timestamp).total_seconds() / 3600
            if gap_hours <= maximum_gap_hours:
                sampled.extend(
                    _intermediate_observations(
                        (lon, lat, radii), (next_lon, next_lat, next_radii), spacing_km
                    )
                )
    reference_lon = observations[len(observations) // 2][1]
    polygons = []
    for lon, lat, radii in sampled:
        polygon = quadrant_polygon(lon, lat, radii, angular_step)
        # Keep every per-point polygon in the same longitude domain before union.
        if abs(polygon.centroid.x - reference_lon) > 180:
            from shapely.affinity import translate

            polygon = translate(polygon, xoff=360 if polygon.centroid.x < reference_lon else -360)
        polygons.append(polygon)
    geometry = unary_union(polygons)
    return FootprintResult(geometry, len(observations), len(storm), tuple(sorted(set(agencies))))
