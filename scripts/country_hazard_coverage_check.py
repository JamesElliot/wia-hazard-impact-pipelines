#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from wia_pipelines.core.worldpop import bbox_coverage_report
from wia_pipelines.hazards.coverage_checks import (
    check_worldpop_coverage,
    plot_flood_item_extents_figure,
    plot_grid_overlay_figure,
    plot_raster_overlay_figure,
    prepare_country_admin_context,
    run_cds_single_month_check,
    run_flood_stac_extent_check,
    run_flood_single_asset_check,
    spei_sample_request,
    utci_sample_request,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "For each ISO3: derive admin bbox, check WorldPop coverage, and fetch one sample "
            "raster/file for drought (SPEI), heat (UTCI), and flood (GFM)."
        )
    )
    p.add_argument(
        "--iso3", action="append", required=True, help="Repeat per country (e.g. --iso3 LBN --iso3 MLI)"
    )
    p.add_argument("--admin-path", default="./data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip")
    p.add_argument("--admin-layer", default="admin2")
    p.add_argument("--iso3-field", default="iso3")
    p.add_argument("--worldpop-dir", default="./data/population")
    p.add_argument("--worldpop-template", default="{iso3_lower}_pop_2025_CN_100m_R2025A_v1.tif")
    p.add_argument("--sample-year", type=int, default=2025)
    p.add_argument("--sample-month", type=int, default=1)
    p.add_argument("--flood-datetime", default="2025-01-01/2025-01-31")
    p.add_argument("--cds-buffer-deg", type=float, default=0.25)
    p.add_argument("--flood-select", choices=["first", "best", "mosaic"], default="mosaic")
    p.add_argument("--flood-mode", choices=["asset", "extents"], default="asset")
    p.add_argument("--make-plots", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--out-dir", default="./outputs/coverage_checks")
    return p


def main() -> int:
    args = build_parser().parse_args()

    admin_path = Path(args.admin_path).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    wp_dir = Path(args.worldpop_dir).resolve()

    rows = []
    report = {"sample_year": args.sample_year, "sample_month": args.sample_month, "countries": []}

    for iso3_raw in args.iso3:
        iso3 = iso3_raw.upper()
        cds_buf_tag = f"b{int(round(args.cds_buffer_deg * 1000)):04d}"
        country_dir = out_dir / iso3
        country_dir.mkdir(parents=True, exist_ok=True)
        fig_dir = country_dir / "figures"
        fig_dir.mkdir(parents=True, exist_ok=True)

        ctx = prepare_country_admin_context(
            iso3=iso3,
            admin_path=admin_path,
            admin_layer=args.admin_layer,
            iso3_field=args.iso3_field,
            buffer_km=0.0,
            cds_buffer_deg=args.cds_buffer_deg,
        )
        admin_bounds = ctx["admin_bounds_wsen"]

        wp_path = wp_dir / args.worldpop_template.format(
            iso3=iso3,
            iso3_lower=iso3.lower(),
            iso3_upper=iso3.upper(),
        )

        worldpop = {
            "ok": False,
            "error": None,
            "coverage_pct": 0.0,
            "full_coverage": False,
            "worldpop_path": str(wp_path),
            "worldpop_bounds_4326": None,
        }
        if wp_path.exists():
            try:
                wp_cov = check_worldpop_coverage(admin_bounds, wp_path)
                worldpop.update({"ok": True, **wp_cov})
            except Exception as exc:
                worldpop["error"] = str(exc)
        else:
            worldpop["error"] = f"WorldPop path not found: {wp_path}"

        # Drought (SPEI single month).
        spei_zip = country_dir / f"{iso3}_spei_{args.sample_year}{args.sample_month:02d}_{cds_buf_tag}.zip"
        spei_req = spei_sample_request(args.sample_year, args.sample_month, ctx["cds_area_nwse"])
        spei_dl = run_cds_single_month_check(
            dataset="derived-drought-historical-monthly",
            request=spei_req,
            output_zip=spei_zip,
        )
        if spei_dl.get("sample_bounds_4326"):
            cov = bbox_coverage_report(admin_bounds, tuple(spei_dl["sample_bounds_4326"]))
            spei_dl["coverage_pct"] = cov["coverage_pct"]
            spei_dl["full_coverage"] = cov["full_coverage"]
        else:
            spei_dl["coverage_pct"] = 0.0
            spei_dl["full_coverage"] = False

        # Heat (UTCI single month).
        utci_zip = country_dir / f"{iso3}_utci_{args.sample_year}{args.sample_month:02d}_{cds_buf_tag}.zip"
        utci_req = utci_sample_request(args.sample_year, args.sample_month, ctx["cds_area_nwse"])
        utci_dl = run_cds_single_month_check(
            dataset="derived-utci-historical",
            request=utci_req,
            output_zip=utci_zip,
        )
        if utci_dl.get("sample_bounds_4326"):
            cov = bbox_coverage_report(admin_bounds, tuple(utci_dl["sample_bounds_4326"]))
            utci_dl["coverage_pct"] = cov["coverage_pct"]
            utci_dl["full_coverage"] = cov["full_coverage"]
        else:
            utci_dl["coverage_pct"] = 0.0
            utci_dl["full_coverage"] = False

        # Flood (single GFM asset from STAC).
        if args.flood_mode == "extents":
            flood = run_flood_stac_extent_check(
                iso3=iso3,
                admin_gdf=ctx["admin_gdf"],
                admin_bounds_wsen=admin_bounds,
                datetime_range=args.flood_datetime,
            )
            flood["coverage_pct"] = float(flood.get("union_bbox_coverage_pct", 0.0))
            flood["full_coverage"] = bool(flood.get("union_full_coverage", False))
        else:
            flood_tif = country_dir / f"{iso3}_gfm_sample_{args.sample_year}{args.sample_month:02d}.tif"
            flood = run_flood_single_asset_check(
                iso3=iso3,
                admin_gdf=ctx["admin_gdf"],
                output_tif=flood_tif,
                admin_bounds_wsen=admin_bounds,
                datetime_range=args.flood_datetime,
                selection_mode=args.flood_select,
            )
            if args.flood_select == "mosaic" and flood.get("mosaic_bbox_coverage_pct") is not None:
                flood["coverage_pct"] = float(flood["mosaic_bbox_coverage_pct"])
                flood["full_coverage"] = bool(flood["coverage_pct"] >= 99.999)
            elif flood.get("sample_bounds_4326"):
                cov = bbox_coverage_report(admin_bounds, tuple(flood["sample_bounds_4326"]))
                flood["coverage_pct"] = cov["coverage_pct"]
                flood["full_coverage"] = cov["full_coverage"]
            else:
                flood["coverage_pct"] = 0.0
                flood["full_coverage"] = False

        country_report = {
            "iso3": iso3,
            "admin_bounds_wsen": admin_bounds,
            "cds_bounds_wsen": ctx["cds_bounds_wsen"],
            "cds_area_nwse": ctx["cds_area_nwse"],
            "cds_buffer_deg": ctx["cds_buffer_deg"],
            "worldpop": worldpop,
            "drought_spei_sample": spei_dl,
            "heat_utci_sample": utci_dl,
            "flood_gfm_sample": flood,
            "figures": {},
        }

        if args.make_plots:
            # WorldPop figures
            if worldpop["ok"]:
                wp_raster_fig = fig_dir / f"{iso3}_worldpop_raster_overlay.png"
                wp_grid_fig = fig_dir / f"{iso3}_worldpop_grid_overlay.png"
                plot_raster_overlay_figure(
                    ctx["admin_gdf"],
                    admin_bounds,
                    source_path=wp_path,
                    source_type="raster",
                    out_png=wp_raster_fig,
                    title=f"{iso3} WorldPop Raster + Admin Boundaries + AOI BBox",
                )
                plot_grid_overlay_figure(
                    ctx["admin_gdf"],
                    admin_bounds,
                    source_path=wp_path,
                    source_type="raster",
                    out_png=wp_grid_fig,
                    title=f"{iso3} WorldPop Grid Lines + Admin Boundaries + AOI BBox",
                )
                country_report["figures"]["worldpop"] = {
                    "raster_overlay": str(wp_raster_fig),
                    "grid_overlay": str(wp_grid_fig),
                }

            # SPEI figures
            if spei_dl.get("ok") and spei_dl.get("first_nc_path"):
                spei_nc = Path(spei_dl["first_nc_path"])
                spei_raster_fig = fig_dir / f"{iso3}_spei_raster_overlay.png"
                spei_grid_fig = fig_dir / f"{iso3}_spei_grid_overlay.png"
                plot_raster_overlay_figure(
                    ctx["admin_gdf"],
                    admin_bounds,
                    source_path=spei_nc,
                    source_type="netcdf",
                    out_png=spei_raster_fig,
                    title=f"{iso3} SPEI Sample Raster + Admin Boundaries + AOI BBox",
                )
                plot_grid_overlay_figure(
                    ctx["admin_gdf"],
                    admin_bounds,
                    source_path=spei_nc,
                    source_type="netcdf",
                    out_png=spei_grid_fig,
                    title=f"{iso3} SPEI Grid Lines + Admin Boundaries + AOI BBox",
                )
                country_report["figures"]["drought_spei"] = {
                    "raster_overlay": str(spei_raster_fig),
                    "grid_overlay": str(spei_grid_fig),
                }

            # UTCI figures
            if utci_dl.get("ok") and utci_dl.get("first_nc_path"):
                utci_nc = Path(utci_dl["first_nc_path"])
                utci_raster_fig = fig_dir / f"{iso3}_utci_raster_overlay.png"
                utci_grid_fig = fig_dir / f"{iso3}_utci_grid_overlay.png"
                plot_raster_overlay_figure(
                    ctx["admin_gdf"],
                    admin_bounds,
                    source_path=utci_nc,
                    source_type="netcdf",
                    out_png=utci_raster_fig,
                    title=f"{iso3} UTCI Sample Raster + Admin Boundaries + AOI BBox",
                )
                plot_grid_overlay_figure(
                    ctx["admin_gdf"],
                    admin_bounds,
                    source_path=utci_nc,
                    source_type="netcdf",
                    out_png=utci_grid_fig,
                    title=f"{iso3} UTCI Grid Lines + Admin Boundaries + AOI BBox",
                )
                country_report["figures"]["heat_utci"] = {
                    "raster_overlay": str(utci_raster_fig),
                    "grid_overlay": str(utci_grid_fig),
                }

            # Flood figures
            if args.flood_mode == "extents":
                if flood.get("ok"):
                    flood_extents_fig = fig_dir / f"{iso3}_flood_item_extents_overlay.png"
                    plot_flood_item_extents_figure(
                        ctx["admin_gdf"],
                        admin_bounds,
                        item_bboxes_4326=flood.get("item_bboxes_4326", []),
                        out_png=flood_extents_fig,
                        title=f"{iso3} GFM STAC Item Extents + Admin Boundaries + AOI BBox",
                    )
                    country_report["figures"]["flood_gfm"] = {
                        "item_extents_overlay": str(flood_extents_fig),
                    }
            elif flood.get("ok") and flood.get("asset_path"):
                flood_tif_path = Path(flood["asset_path"])
                flood_raster_fig = fig_dir / f"{iso3}_flood_raster_overlay.png"
                flood_grid_fig = fig_dir / f"{iso3}_flood_grid_overlay.png"
                plot_raster_overlay_figure(
                    ctx["admin_gdf"],
                    admin_bounds,
                    source_path=flood_tif_path,
                    source_type="raster",
                    out_png=flood_raster_fig,
                    title=f"{iso3} Flood Sample Raster + Admin Boundaries + AOI BBox",
                )
                plot_grid_overlay_figure(
                    ctx["admin_gdf"],
                    admin_bounds,
                    source_path=flood_tif_path,
                    source_type="raster",
                    out_png=flood_grid_fig,
                    title=f"{iso3} Flood Grid Lines + Admin Boundaries + AOI BBox",
                )
                country_report["figures"]["flood_gfm"] = {
                    "raster_overlay": str(flood_raster_fig),
                    "grid_overlay": str(flood_grid_fig),
                }
        report["countries"].append(country_report)

        rows.extend(
            [
                {
                    "iso3": iso3,
                    "hazard": "worldpop",
                    "ok": worldpop["ok"],
                    "coverage_pct": worldpop["coverage_pct"],
                    "full_coverage": worldpop["full_coverage"],
                    "error": worldpop["error"],
                    "path_or_href": worldpop["worldpop_path"],
                },
                {
                    "iso3": iso3,
                    "hazard": "drought_spei",
                    "ok": spei_dl["ok"],
                    "coverage_pct": spei_dl["coverage_pct"],
                    "full_coverage": spei_dl["full_coverage"],
                    "error": spei_dl["error"],
                    "path_or_href": spei_dl["zip_path"],
                },
                {
                    "iso3": iso3,
                    "hazard": "heat_utci",
                    "ok": utci_dl["ok"],
                    "coverage_pct": utci_dl["coverage_pct"],
                    "full_coverage": utci_dl["full_coverage"],
                    "error": utci_dl["error"],
                    "path_or_href": utci_dl["zip_path"],
                },
                {
                    "iso3": iso3,
                    "hazard": "flood_gfm",
                    "ok": flood["ok"],
                    "coverage_pct": flood["coverage_pct"],
                    "full_coverage": flood["full_coverage"],
                    "error": flood["error"],
                    "path_or_href": flood.get("asset_path") or flood.get("asset_href"),
                },
            ]
        )

    json_path = out_dir / "coverage_report.json"
    csv_path = out_dir / "coverage_summary.csv"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    pd.DataFrame(rows).to_csv(csv_path, index=False)

    print(f"Wrote JSON report: {json_path}")
    print(f"Wrote CSV summary: {csv_path}")
    print(pd.DataFrame(rows).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
