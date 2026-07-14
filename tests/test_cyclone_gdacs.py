from pathlib import Path
from urllib.parse import parse_qs, urlparse

import geopandas as gpd
import pandas as pd
from shapely.geometry import box, mapping

from wia_pipelines.hazards.cyclone.gdacs import extract_wind_buffers, fetch_event_list, match_event
from wia_pipelines.hazards.cyclone.pipeline import RunInputs, run_pipeline
from wia_pipelines.hazards.cyclone.tracks import TrackWindow

from test_cyclone_pipeline import _inputs


def _event(eventid=1001, name="TEST-26"):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [0, 0]},
        "properties": {
            "eventid": eventid,
            "episodeid": 3,
            "eventname": name,
            "fromdate": "2026-01-01T00:00:00",
            "todate": "2026-01-03T00:00:00",
            "source": "JTWC",
        },
    }


def test_event_list_fetch_exhausts_pagination():
    calls = []

    def fake_fetch(url):
        calls.append(url)
        page = int(parse_qs(urlparse(url).query)["pageNumber"][0])
        start = 0 if page == 1 else 100
        count = 100 if page == 1 else 1
        return {"type": "FeatureCollection", "features": [_event(start + i) for i in range(count)]}

    window = TrackWindow(pd.Timestamp("2025-04-01"), pd.Timestamp("2026-03-31"))
    events = fetch_event_list(window, fetch_json=fake_fetch)
    assert len(calls) == 2
    assert len(events) == 101


def test_name_and_date_matching_and_consolidated_buffer_extraction():
    storm = pd.DataFrame(
        {
            "NAME": ["TEST", "TEST"],
            "ISO_TIME": pd.to_datetime(["2026-01-01", "2026-01-04"]),
        }
    )
    event = _event()
    assert match_event(storm, [event]) == event

    def feature(label, feature_class, geometry):
        return {
            "type": "Feature",
            "properties": {"polygonlabel": label, "Class": feature_class},
            "geometry": mapping(geometry),
        }

    payload = {
        "features": [
            feature("60 km/h", "Poly_Green", box(-1, -1, 1, 1)),
            feature("04/01 00:00", "Poly_Green", box(-2, -2, 2, 2)),
            feature("120 km/h", "Poly_Red", box(-0.5, -0.5, 0.5, 0.5)),
            feature("60 km/h", "Line_Line_1", box(-3, -3, 3, 3)),
        ]
    }
    rows = extract_wind_buffers(
        payload,
        sid="2026001N00000",
        event_properties=event["properties"],
        retrieved_utc="2026-07-13T00:00:00+00:00",
        source_url="https://example.test/geometry",
    )
    assert {row["threshold_kmh"] for row in rows} == {63, 119}
    assert {row["native_threshold_kmh"] for row in rows} == {60, 120}
    assert next(row for row in rows if row["threshold_kmh"] == 63)["geometry"].area == 4


def test_local_gdacs_polygon_fills_missing_primary_footprint(tmp_path: Path):
    inputs = _inputs(tmp_path, complete=False)
    frame = pd.read_csv(inputs.ibtracs)
    frame.loc[0, "USA_R34_NE"] = None
    frame.to_csv(inputs.ibtracs, index=False)

    gdacs_path = tmp_path / "gdacs.gpkg"
    gpd.GeoDataFrame(
        {
            "SID": ["2026001N00000"],
            "threshold_kmh": [63],
            "native_threshold_kmh": [60],
            "gdacs_eventid": [1001],
        },
        geometry=[box(-0.8, 0.2, -0.2, 0.8)],
        crs=4326,
    ).to_file(gdacs_path, driver="GPKG")
    fallback_inputs = RunInputs(**{**inputs.__dict__, "gdacs_footprints": gdacs_path})
    output = run_pipeline(fallback_inputs)
    table = pd.read_csv(output / "tables" / "HI06_TST_2026-06-30.csv")
    storms = pd.read_csv(output / "qc" / "HI06_TST_storms_2026-06-30.csv")
    assert table["flag_method_fallback"].all()
    assert table["flag_windradii"].eq("fallback").all()
    assert str(storms.loc[0, "fallback_thresholds_kmh"]) == "63"
    assert str(storms.loc[0, "gdacs_eventids"]) == "1001"
