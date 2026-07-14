from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import pandas as pd
from pyproj import CRS
import shapely
from shapely.geometry import Point


KNOT_TO_KMH = 1.852
THRESHOLD_TO_KNOT = {63: 34, 93: 50, 119: 64}
QUADRANTS = ("NE", "SE", "SW", "NW")
PREFERRED_AGENCIES = ("USA", "WMO", "TOKYO", "CMA", "HKO", "NEWDELHI", "REUNION", "BOM", "NADI")


@dataclass(frozen=True)
class TrackWindow:
    start: pd.Timestamp
    end: pd.Timestamp


def rolling_window(end: str | pd.Timestamp, months: int = 12) -> TrackWindow:
    if int(months) < 1:
        raise ValueError("months must be at least 1")
    end_ts = pd.Timestamp(end).normalize()
    if pd.isna(end_ts):
        raise ValueError(f"Invalid window end: {end}")
    start_ts = end_ts - pd.DateOffset(months=months) + pd.Timedelta(days=1)
    return TrackWindow(start=start_ts, end=end_ts + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1))


def read_ibtracs(path: Path, window: TrackWindow) -> pd.DataFrame:
    frame = pd.read_csv(path, low_memory=False, na_values=[-999, -999.0, "-999", " ", ""])
    frame.columns = [str(column).strip().upper() for column in frame.columns]
    required = {"SID", "ISO_TIME", "LAT", "LON"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"IBTrACS input is missing required columns: {sorted(missing)}")
    frame["ISO_TIME"] = pd.to_datetime(frame["ISO_TIME"], errors="coerce", utc=True).dt.tz_localize(None)
    for column in ["LAT", "LON"] + _numeric_track_columns(frame):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["SID", "ISO_TIME", "LAT", "LON"])
    if "TRACK_TYPE" in frame.columns:
        track_type = frame["TRACK_TYPE"].astype(str).str.lower()
        frame = frame.loc[~track_type.str.endswith("spur")].copy()
    frame = frame.loc[frame["ISO_TIME"].between(window.start, window.end)].copy()
    return frame.sort_values(["SID", "ISO_TIME"]).reset_index(drop=True)


def _numeric_track_columns(frame: pd.DataFrame) -> list[str]:
    result = []
    for column in frame.columns:
        if column.endswith("_WIND") or any(
            f"_R{speed}_{quad}" in column for speed in (34, 50, 64) for quad in QUADRANTS
        ):
            result.append(column)
    return result


def select_candidate_points(
    tracks: pd.DataFrame,
    country: gpd.GeoDataFrame,
    buffer_km: float,
) -> pd.DataFrame:
    if tracks.empty:
        return tracks.copy()
    country_4326 = country.to_crs(4326)
    country_union = shapely.union_all(country_4326.geometry.to_numpy(), grid_size=1e-8)
    if not country_union.is_valid:
        country_union = shapely.make_valid(country_union)
    centre = country_union.centroid
    local_crs = CRS.from_proj4(
        f"+proj=aeqd +lat_0={centre.y:.8f} +lon_0={centre.x:.8f} +datum=WGS84 +units=m +no_defs"
    )
    projected = country_4326.to_crs(local_crs)
    projected_union = shapely.union_all(projected.geometry.to_numpy(), grid_size=1.0)
    if not projected_union.is_valid:
        projected_union = shapely.make_valid(projected_union)
    buffered = projected_union.buffer(buffer_km * 1000)
    points = gpd.GeoSeries(
        [Point(lon, lat) for lon, lat in zip(tracks["LON"], tracks["LAT"])],
        crs=4326,
    ).to_crs(local_crs)
    candidate_sids = tracks.loc[points.intersects(buffered).to_numpy(), "SID"].unique()
    return tracks.loc[tracks["SID"].isin(candidate_sids)].copy()


def maximum_wind_knots(storm: pd.DataFrame) -> float | None:
    columns = [column for column in ("USA_WIND", "WMO_WIND") if column in storm]
    columns.extend(column for column in storm.columns if column.endswith("_WIND") and column not in columns)
    values = (
        pd.concat([storm[column] for column in columns], ignore_index=True)
        if columns
        else pd.Series(dtype=float)
    )
    values = pd.to_numeric(values, errors="coerce").dropna()
    return float(values.max()) if not values.empty else None


def radii_for_row(row: pd.Series, threshold_kmh: int) -> tuple[dict[str, float], str] | None:
    speed = THRESHOLD_TO_KNOT[threshold_kmh]
    agencies = list(PREFERRED_AGENCIES)
    reported = str(row.get("WMO_AGENCY", "")).strip().upper().replace(" ", "")
    if reported and reported not in agencies:
        agencies.insert(1, reported)
    dynamic = sorted({column.split(f"_R{speed}_", 1)[0] for column in row.index if f"_R{speed}_" in column})
    agencies.extend(agency for agency in dynamic if agency not in agencies)
    for agency in agencies:
        values = {}
        for quadrant in QUADRANTS:
            value = pd.to_numeric(row.get(f"{agency}_R{speed}_{quadrant}"), errors="coerce")
            if pd.notna(value) and float(value) > 0:
                values[quadrant] = float(value) * 1.852  # IBTrACS radii are nautical miles
        if len(values) == 4:
            return values, agency
    return None


def radii_completeness(storm: pd.DataFrame, threshold_kmh: int) -> float:
    if storm.empty:
        return 0.0
    return sum(radii_for_row(row, threshold_kmh) is not None for _, row in storm.iterrows()) / len(storm)
