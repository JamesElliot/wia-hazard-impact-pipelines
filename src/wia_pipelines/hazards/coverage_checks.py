from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.cds import download_cds, extract_zip_to_dir
from ..core.worldpop import bbox_coverage_report, worldpop_profile_and_bounds


def netcdf_bounds_4326(path: Path) -> tuple[float, float, float, float]:
    import xarray as xr

    ds = xr.open_dataset(path)
    try:
        lon_name = next((k for k in ("lon", "longitude", "x") if k in ds.coords), None)
        lat_name = next((k for k in ("lat", "latitude", "y") if k in ds.coords), None)
        if lon_name is None or lat_name is None:
            raise ValueError(f"Could not infer lon/lat coordinate names in {path.name}")
        lon = ds.coords[lon_name].values
        lat = ds.coords[lat_name].values
        return (float(lon.min()), float(lat.min()), float(lon.max()), float(lat.max()))
    finally:
        ds.close()


def raster_bounds_4326(path: Path) -> tuple[float, float, float, float]:
    import geopandas as gpd
    import rasterio
    from shapely.geometry import box

    with rasterio.open(path) as src:
        bounds_geom = box(*src.bounds)
        if src.crs is None:
            return tuple(float(v) for v in src.bounds)
        bounds = gpd.GeoSeries([bounds_geom], crs=src.crs).to_crs("EPSG:4326").iloc[0].bounds
    return tuple(float(v) for v in bounds)


def evaluate_coverage_gate(coverage_pct: float, target_pct: float, hard_min_pct: float) -> str:
    """Classify a coverage percentage against the two-tier gate shared by every hazard's
    preflight-coverage checks (ARCH-012): below `hard_min_pct` is `"fail"` (the caller should
    raise), between `hard_min_pct` and `target_pct` is `"warn"` (continue, but flag it), and
    at/above `target_pct` is `"ok"`.
    """
    coverage_pct = float(coverage_pct)
    if coverage_pct < float(hard_min_pct):
        return "fail"
    if coverage_pct < float(target_pct):
        return "warn"
    return "ok"


def check_worldpop_coverage(
    admin_bounds_wsen: tuple[float, float, float, float], worldpop_path: Path
) -> dict[str, Any]:
    wp = worldpop_profile_and_bounds(worldpop_path)
    report = bbox_coverage_report(admin_bounds_wsen, wp["bounds_4326"])
    return {
        "worldpop_path": str(worldpop_path),
        "worldpop_bounds_4326": wp["bounds_4326"],
        "coverage_pct": report["coverage_pct"],
        "full_coverage": report["full_coverage"],
        "warnings": report["warnings"],
    }


def run_cds_single_month_check(
    dataset: str,
    request: dict[str, Any],
    output_zip: Path,
) -> dict[str, Any]:
    if output_zip.exists() and output_zip.stat().st_size > 0:
        ok, err = True, None
    else:
        ok, err = download_cds(dataset, request, output_zip)
    result: dict[str, Any] = {
        "ok": ok,
        "error": err,
        "zip_path": str(output_zip),
        "zip_exists": output_zip.exists(),
        "zip_size": output_zip.stat().st_size if output_zip.exists() else 0,
        "n_nc_files": 0,
        "first_nc_path": None,
        "sample_bounds_4326": None,
    }
    if not ok:
        return result

    extracted = extract_zip_to_dir(output_zip, output_zip.parent / "extracted")
    result["n_nc_files"] = len(extracted)
    if extracted:
        result["first_nc_path"] = str(extracted[0])
        result["sample_bounds_4326"] = netcdf_bounds_4326(extracted[0])
    return result


def run_flood_single_asset_check(
    iso3: str,
    admin_gdf,
    output_tif: Path,
    admin_bounds_wsen: tuple[float, float, float, float],
    stac_api_url: str = "https://stac.eodc.eu/api/v1",
    collection_id: str = "GFM",
    asset_key: str = "ensemble_flood_extent",
    datetime_range: str = "2025-01-01/2025-01-31",
    selection_mode: str = "best",
) -> dict[str, Any]:
    import requests
    from pystac_client import Client
    from shapely.geometry import box, mapping
    from shapely.ops import unary_union

    country_geom_4326 = admin_gdf.to_crs("EPSG:4326").geometry.union_all()
    admin_box = box(*admin_bounds_wsen)

    out = {
        "ok": False,
        "error": None,
        "asset_path": str(output_tif),
        "asset_href": None,
        "sample_bounds_4326": None,
        "item_id": None,
        "item_count": 0,
        "selection_mode": selection_mode,
        "collection_id": collection_id,
        "asset_key": asset_key,
        "item_bbox_coverage_pct": None,
        "mosaic_bbox_coverage_pct": None,
        "cached_file_used": False,
    }

    if output_tif.exists() and output_tif.stat().st_size > 0:
        out["sample_bounds_4326"] = raster_bounds_4326(output_tif)
        out["ok"] = True
        out["cached_file_used"] = True
        return out

    def _select_candidate_by_mode(cands, mode: str):
        if mode == "first":
            return cands[0][0], max(cands, key=lambda x: x[1])[1]
        chosen_item, best_cov = max(cands, key=lambda x: x[1])
        return chosen_item, best_cov

    try:
        client = Client.open(stac_api_url)
        search = client.search(
            collections=[collection_id],
            intersects=mapping(country_geom_4326),
            datetime=datetime_range,
        )
        items = list(search.items())
        if not items:
            out["error"] = f"No STAC items found for {iso3} in {datetime_range}."
            return out
        out["item_count"] = len(items)

        candidates = []
        for item in items:
            if asset_key in item.assets:
                if item.bbox is None:
                    continue
                ibox = box(*item.bbox)
                inter = admin_box.intersection(ibox)
                cov_pct = 0.0 if admin_box.area == 0 else float((inter.area / admin_box.area) * 100.0)
                candidates.append((item, cov_pct))
        if not candidates:
            out["error"] = f"No STAC items with asset '{asset_key}' found."
            return out

        if selection_mode not in {"first", "best", "mosaic"}:
            out["error"] = f"Unsupported selection_mode '{selection_mode}'."
            return out

        chosen, best_cov = _select_candidate_by_mode(candidates, selection_mode)
        out["item_bbox_coverage_pct"] = best_cov

        if selection_mode == "mosaic":
            union = unary_union([box(*c[0].bbox) for c in candidates if c[0].bbox])
            inter = admin_box.intersection(union)
            mosaic_cov = 0.0 if admin_box.area == 0 else float((inter.area / admin_box.area) * 100.0)
            out["mosaic_bbox_coverage_pct"] = mosaic_cov

        asset = chosen.assets[asset_key]
        href = asset.href
        out["asset_href"] = href
        out["item_id"] = chosen.id
        output_tif.parent.mkdir(parents=True, exist_ok=True)

        with requests.get(href, stream=True, timeout=180) as resp:
            resp.raise_for_status()
            with output_tif.open("wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 512):
                    if chunk:
                        f.write(chunk)

        out["sample_bounds_4326"] = raster_bounds_4326(output_tif)
        out["ok"] = True
        return out
    except Exception as exc:
        out["error"] = str(exc)
        return out


def run_flood_stac_extent_check(
    iso3: str,
    admin_gdf,
    admin_bounds_wsen: tuple[float, float, float, float],
    stac_api_url: str = "https://stac.eodc.eu/api/v1",
    collection_id: str = "GFM",
    asset_key: str = "ensemble_flood_extent",
    datetime_range: str = "2025-01-01/2025-01-31",
) -> dict[str, Any]:
    from pystac_client import Client
    from shapely.geometry import box, mapping
    from shapely.ops import unary_union

    country_geom_4326 = admin_gdf.to_crs("EPSG:4326").geometry.union_all()
    admin_box = box(*admin_bounds_wsen)

    out = {
        "ok": False,
        "error": None,
        "collection_id": collection_id,
        "asset_key": asset_key,
        "item_count": 0,
        "item_ids": [],
        "item_bboxes_4326": [],
        "item_bbox_coverages_pct": [],
        "union_bbox_coverage_pct": 0.0,
        "union_full_coverage": False,
        "datetime_range": datetime_range,
    }
    try:
        client = Client.open(stac_api_url)
        search = client.search(
            collections=[collection_id],
            intersects=mapping(country_geom_4326),
            datetime=datetime_range,
        )
        items = list(search.items())
        if not items:
            out["error"] = f"No STAC items found for {iso3} in {datetime_range}."
            return out

        candidates = []
        for item in items:
            if asset_key not in item.assets:
                continue
            if item.bbox is None:
                continue
            ibox = box(*item.bbox)
            inter = admin_box.intersection(ibox)
            cov_pct = 0.0 if admin_box.area == 0 else float((inter.area / admin_box.area) * 100.0)
            candidates.append((item, cov_pct))

        if not candidates:
            out["error"] = f"No STAC items with asset '{asset_key}' and bbox metadata found."
            return out

        out["item_count"] = len(candidates)
        out["item_ids"] = [c[0].id for c in candidates]
        out["item_bboxes_4326"] = [list(c[0].bbox) for c in candidates]
        out["item_bbox_coverages_pct"] = [float(c[1]) for c in candidates]

        union = unary_union([box(*c[0].bbox) for c in candidates])
        inter = admin_box.intersection(union)
        union_cov = 0.0 if admin_box.area == 0 else float((inter.area / admin_box.area) * 100.0)
        out["union_bbox_coverage_pct"] = union_cov
        out["union_full_coverage"] = union_cov >= 99.999
        out["ok"] = True
        return out
    except Exception as exc:
        out["error"] = str(exc)
        return out
