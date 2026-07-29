import geopandas as gpd
import numpy as np
from shapely.geometry import box

from wia_pipelines.hazards.cyclone.aggregate import _storm_admin_intersection_counts


def test_counts_intersecting_storms_per_admin():
    admin = gpd.GeoDataFrame(
        {"id": [0, 1, 2]},
        geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1), box(5, 5, 6, 6)],
        crs=4326,
    )
    storms = {
        "storm1": box(0.5, 0.5, 1.5, 1.5),  # straddles admin 0 and 1
        "storm2": box(5.2, 5.2, 5.8, 5.8),  # inside admin 2 only
        "storm3": None,  # no footprint geometry for this storm -- must be skipped
    }
    counts = _storm_admin_intersection_counts(admin, storms)
    np.testing.assert_array_equal(counts, [1, 1, 1])


def test_matches_the_original_per_admin_algorithm_across_the_antimeridian():
    # PERF-009: this replaces a per-(storm, admin) loop that shifted the
    # storm geometry by +-360 relative to each admin polygon's own centroid.
    # Reproduce that original algorithm here (rather than importing it, since
    # it no longer exists in aggregate.py) and confirm the two agree on a
    # synthetic "country" straddling the antimeridian, where admin polygons'
    # raw stored longitudes span both sides of the +-180 boundary.
    from shapely import affinity

    def original_algorithm(admin_4326, storm_geometries):
        def normalise(geometry, raster_centre_x):
            if geometry.is_empty:
                return geometry
            centre = geometry.centroid.x
            while centre - raster_centre_x > 180:
                geometry = affinity.translate(geometry, xoff=-360)
                centre -= 360
            while raster_centre_x - centre > 180:
                geometry = affinity.translate(geometry, xoff=360)
                centre += 360
            return geometry

        counts = np.zeros(len(admin_4326), dtype=np.int32)
        for geometry in storm_geometries.values():
            if geometry is None or geometry.is_empty:
                continue
            for index, admin_geometry in enumerate(admin_4326.geometry):
                adjusted = normalise(geometry, admin_geometry.centroid.x)
                if adjusted.intersects(admin_geometry):
                    counts[index] += 1
        return counts

    admin = gpd.GeoDataFrame(
        {"id": range(4)},
        geometry=[
            box(179.0, -18, 179.5, -17.5),
            box(-180.0, -18, -179.5, -17.5),
            box(178.0, -19, 178.5, -18.5),
            box(-179.0, -19, -178.5, -18.5),
        ],
        crs=4326,
    )
    storms = {
        "storm1": box(179.6, -18.2, 180.0, -17.6),
        "storm2": box(-179.9, -18.6, -179.4, -18.0),
        "storm3": box(178.1, -18.9, 178.4, -18.6),
    }

    expected = original_algorithm(admin, storms)
    actual = _storm_admin_intersection_counts(admin, storms)
    np.testing.assert_array_equal(actual, expected)
