from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import geopandas as gpd
import pandas as pd
from shapely.geometry import shape
from shapely.ops import unary_union

from .tracks import TrackWindow


API_ROOT = "https://www.gdacs.org/gdacsapi/api"
GDACS_TO_PIPELINE_THRESHOLD = {60: 63, 90: 93, 120: 119}
POLYGON_LABEL_TO_THRESHOLD = {
    "60 km/h": 60,
    "90 km/h": 90,
    "120 km/h": 120,
}


@dataclass(frozen=True)
class GdacsFetchResult:
    footprints: gpd.GeoDataFrame
    audit: pd.DataFrame
    retrieved_utc: str


def _get_json(url: str, timeout: float = 60) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "wia-hi06/0.1 GDACS fallback"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except Exception as error:
        raise RuntimeError(f"GDACS request failed: {url}: {error}") from error


def fetch_event_list(
    window: TrackWindow,
    *,
    fetch_json: Callable[[str], dict[str, Any]] = _get_json,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    page_number = 1
    while True:
        query = urlencode(
            {
                "eventlist": "TC",
                "fromdate": window.start.date().isoformat(),
                "todate": window.end.date().isoformat(),
                "alertlevel": "red;orange;green",
                "pageSize": page_size,
                "pageNumber": page_number,
            }
        )
        payload = fetch_json(f"{API_ROOT}/events/geteventlist/SEARCH?{query}")
        page = payload.get("features", [])
        if not isinstance(page, list):
            raise ValueError("GDACS event-list response has no GeoJSON feature list")
        features.extend(page)
        if len(page) < page_size:
            break
        page_number += 1
    deduplicated: dict[int, dict[str, Any]] = {}
    for feature in features:
        properties = feature.get("properties", {})
        event_id = properties.get("eventid")
        if event_id is not None:
            deduplicated[int(event_id)] = feature
    return list(deduplicated.values())


def _normalise_name(value: Any) -> str:
    text = re.sub(r"-\d{2}$", "", str(value or "").strip().upper())
    return re.sub(r"[^A-Z0-9]+", "", text)


def match_event(storm: pd.DataFrame, events: list[dict[str, Any]]) -> dict[str, Any] | None:
    names = storm.get("NAME", pd.Series(dtype=str)).dropna().astype(str)
    storm_name = _normalise_name(names.iloc[0] if not names.empty else "")
    if not storm_name:
        return None
    storm_start = pd.Timestamp(storm["ISO_TIME"].min()) - pd.Timedelta(days=3)
    storm_end = pd.Timestamp(storm["ISO_TIME"].max()) + pd.Timedelta(days=3)
    matches = []
    for feature in events:
        properties = feature.get("properties", {})
        if _normalise_name(properties.get("eventname")) != storm_name:
            continue
        event_start = pd.to_datetime(properties.get("fromdate"), errors="coerce")
        event_end = pd.to_datetime(properties.get("todate"), errors="coerce")
        if pd.isna(event_start) or pd.isna(event_end):
            continue
        event_start = event_start.tz_localize(None) if event_start.tzinfo else event_start
        event_end = event_end.tz_localize(None) if event_end.tzinfo else event_end
        if event_start <= storm_end and event_end >= storm_start:
            matches.append((abs((event_start - storm_start).total_seconds()), feature))
    return min(matches, key=lambda item: item[0])[1] if matches else None


def extract_wind_buffers(
    payload: dict[str, Any],
    *,
    sid: str,
    event_properties: dict[str, Any],
    retrieved_utc: str,
    source_url: str,
) -> list[dict[str, Any]]:
    by_native_threshold: dict[int, list[Any]] = {threshold: [] for threshold in (60, 90, 120)}
    for feature in payload.get("features", []):
        properties = feature.get("properties", {})
        label = str(properties.get("polygonlabel", "")).strip()
        native_threshold = POLYGON_LABEL_TO_THRESHOLD.get(label)
        if native_threshold is None:
            continue
        expected_class = {60: "Poly_Green", 90: "Poly_Orange", 120: "Poly_Red"}[native_threshold]
        if properties.get("Class") != expected_class or not feature.get("geometry"):
            continue
        geometry = shape(feature["geometry"])
        if not geometry.is_empty:
            by_native_threshold[native_threshold].append(geometry)

    rows = []
    for native_threshold, geometries in by_native_threshold.items():
        if not geometries:
            continue
        geometry = unary_union(geometries)
        if not geometry.is_valid:
            geometry = geometry.buffer(0)
        rows.append(
            {
                "SID": str(sid),
                "threshold_kmh": GDACS_TO_PIPELINE_THRESHOLD[native_threshold],
                "native_threshold_kmh": native_threshold,
                "gdacs_eventid": int(event_properties["eventid"]),
                "gdacs_episodeid": int(event_properties["episodeid"]),
                "gdacs_eventname": event_properties.get("eventname"),
                "gdacs_source": event_properties.get("source"),
                "source_url": source_url,
                "retrieved_utc": retrieved_utc,
                "geometry": geometry,
            }
        )
    return rows


def fetch_gdacs_fallbacks(
    storms: pd.DataFrame,
    window: TrackWindow,
    footprint_path: Path,
    audit_path: Path,
    *,
    fetch_json: Callable[[str], dict[str, Any]] = _get_json,
) -> GdacsFetchResult:
    retrieved_utc = datetime.now(timezone.utc).isoformat()
    events = fetch_event_list(window, fetch_json=fetch_json)
    rows: list[dict[str, Any]] = []
    audit_rows = []
    for sid, storm in storms.groupby("SID", sort=True):
        names = storm.get("NAME", pd.Series(dtype=str)).dropna().astype(str)
        storm_name = names.iloc[0] if not names.empty else None
        event = match_event(storm, events)
        if event is None:
            audit_rows.append(
                {
                    "SID": sid,
                    "ibtracs_name": storm_name,
                    "match_status": "no_name_date_match",
                    "gdacs_eventid": None,
                    "gdacs_episodeid": None,
                    "gdacs_eventname": None,
                    "thresholds_kmh": None,
                    "source_url": None,
                }
            )
            continue
        properties = event["properties"]
        source_url = properties.get("url", {}).get("geometry") or (
            f"{API_ROOT}/polygons/getgeometry?"
            + urlencode(
                {
                    "eventtype": "TC",
                    "eventid": properties["eventid"],
                    "episodeid": properties["episodeid"],
                }
            )
        )
        event_rows = extract_wind_buffers(
            fetch_json(source_url),
            sid=str(sid),
            event_properties=properties,
            retrieved_utc=retrieved_utc,
            source_url=source_url,
        )
        rows.extend(event_rows)
        thresholds = ",".join(str(row["threshold_kmh"]) for row in event_rows)
        audit_rows.append(
            {
                "SID": sid,
                "ibtracs_name": storm_name,
                "match_status": ("matched_with_wind_buffers" if event_rows else "matched_no_wind_buffers"),
                "gdacs_eventid": properties["eventid"],
                "gdacs_episodeid": properties["episodeid"],
                "gdacs_eventname": properties.get("eventname"),
                "thresholds_kmh": thresholds or None,
                "source_url": source_url,
            }
        )

    columns = [
        "SID",
        "threshold_kmh",
        "native_threshold_kmh",
        "gdacs_eventid",
        "gdacs_episodeid",
        "gdacs_eventname",
        "gdacs_source",
        "source_url",
        "retrieved_utc",
        "geometry",
    ]
    footprints = gpd.GeoDataFrame(rows, columns=columns, geometry="geometry", crs=4326)
    audit = pd.DataFrame(audit_rows)
    audit.to_csv(audit_path, index=False)
    if not footprints.empty:
        footprints.to_file(footprint_path, layer="gdacs_fallbacks", driver="GPKG")
    return GdacsFetchResult(footprints=footprints, audit=audit, retrieved_utc=retrieved_utc)
