from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CATALOG_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"


def build_catalog_url(
    start_date: str,
    end_date: str,
    bounds: tuple[float, float, float, float],
    catalog_url: str = CATALOG_URL,
) -> str:
    west, south, east, north = bounds
    params = {
        "format": "geojson",
        "starttime": start_date,
        "endtime": f"{end_date}T23:59:59.999Z",
        "minlatitude": south,
        "maxlatitude": north,
        "minlongitude": west,
        "maxlongitude": east,
        "orderby": "time-asc",
        "eventtype": "earthquake",
    }
    return f"{catalog_url}?{urllib.parse.urlencode(params)}"


def fetch_bytes(url: str, timeout_seconds: int = 120) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "wia-hazard-layers/0.1"})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read()


def fetch_json(url: str, timeout_seconds: int = 120) -> dict[str, Any]:
    return json.loads(fetch_bytes(url, timeout_seconds).decode("utf-8"))


def is_actual_event(feature: dict[str, Any]) -> tuple[bool, str]:
    props = feature.get("properties") or {}
    event_type = str(props.get("type") or "").lower()
    title = str(props.get("title") or "").lower()
    if event_type != "earthquake":
        return False, f"event_type:{event_type or 'missing'}"
    if any(token in title for token in ("scenario", "exercise", "test event")):
        return False, "scenario_or_test"
    return True, "actual_earthquake"


def select_shakemap_product(detail: dict[str, Any]) -> dict[str, Any] | None:
    products = ((detail.get("properties") or {}).get("products") or {}).get("shakemap") or []
    candidates = [p for p in products if str(p.get("status", "UPDATE")).upper() != "DELETE"]
    if not candidates:
        return None
    return max(candidates, key=lambda p: (float(p.get("preferredWeight", 0)), int(p.get("updateTime", 0))))


def select_grid_content(product: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    contents = product.get("contents") or {}
    preferences = (
        "download/grid.xml",
        "download/grid.xml.zip",
        "download/shape.zip",
    )
    for suffix in preferences:
        matches = [(name, value) for name, value in contents.items() if name.lower().endswith(suffix)]
        if matches:
            return matches[0]
    return None


@dataclass(frozen=True)
class ShakeGrid:
    mmi: Any
    transform: Any
    crs: str
    nodata: float
    metadata: dict[str, Any]


def parse_grid_xml(data: bytes) -> ShakeGrid:
    import numpy as np
    from affine import Affine

    root = ET.fromstring(data)
    spec = next((el for el in root.iter() if el.tag.endswith("grid_specification")), None)
    grid_data = next((el for el in root.iter() if el.tag.endswith("grid_data")), None)
    fields = [el for el in root.iter() if el.tag.endswith("grid_field")]
    if spec is None or grid_data is None or not grid_data.text:
        raise ValueError("ShakeMap grid.xml is missing grid specification or data.")
    field_names = [str(el.attrib.get("name", "")).upper() for el in fields]
    if "MMI" not in field_names:
        raise ValueError(f"ShakeMap grid.xml has no MMI field: {field_names}")
    mmi_index = field_names.index("MMI")
    nlon = int(spec.attrib["nlon"])
    nlat = int(spec.attrib["nlat"])
    values = np.fromstring(grid_data.text, sep=" ", dtype="float64")
    nfields = len(fields)
    expected = nlon * nlat * nfields
    if values.size != expected:
        raise ValueError(f"ShakeMap grid data has {values.size} values; expected {expected}.")
    rows = values.reshape((nlat * nlon, nfields))
    mmi = rows[:, mmi_index].reshape((nlat, nlon)).astype("float32")
    lon_min = float(spec.attrib["lon_min"])
    lat_max = float(spec.attrib["lat_max"])
    dx = float(spec.attrib["nominal_lon_spacing"])
    dy = float(spec.attrib["nominal_lat_spacing"])
    transform = Affine(dx, 0.0, lon_min - dx / 2.0, 0.0, -dy, lat_max + dy / 2.0)
    return ShakeGrid(
        mmi=mmi,
        transform=transform,
        crs="EPSG:4326",
        nodata=-9999.0,
        metadata={"nlon": nlon, "nlat": nlat, "field_names": field_names},
    )


def download_cached(
    url: str,
    path: Path,
    timeout_seconds: int = 120,
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0 and not refresh:
        data = path.read_bytes()
        source = "cache"
    else:
        data = fetch_bytes(url, timeout_seconds)
        path.write_bytes(data)
        source = "download"
    return {
        "path": str(path),
        "source": source,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "retrieved_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }


def fetch_json_cached(
    url: str,
    path: Path,
    timeout_seconds: int = 120,
    *,
    refresh: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    result = download_cached(url, path, timeout_seconds, refresh=refresh)
    return json.loads(Path(result["path"]).read_text(encoding="utf-8")), result
