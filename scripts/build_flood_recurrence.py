#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from wia_pipelines.hazards.flood_recurrence import build_flood_recurrence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Map how many annual windows each pixel was flooded in.")
    parser.add_argument("--iso3", default="SSD")
    parser.add_argument("--start-year", type=int, default=2021)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--output-root", default="./outputs")
    parser.add_argument(
        "--admin-path", default="./data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip"
    )
    parser.add_argument("--admin-layer", default="admin2")
    parser.add_argument("--iso3-field", default="iso3")
    parser.add_argument("--rivers-path", default="./data/HydroRIVERS_v10/HydroRIVERS_v10.gdb")
    parser.add_argument("--lakes-path", default="./data/HydroLAKES_polys_v10/HydroLAKES_polys_v10.gdb")
    parser.add_argument(
        "--lakes-fallback-path",
        default=("/vsizip/vsicurl/https://data.hydrosheds.org/file/hydrolakes/HydroLAKES_polys_v10.gdb.zip"),
        help="Optional GDAL path used when the local HydroLAKES geodatabase is incomplete.",
    )
    parser.add_argument("--river-min-discharge-cms", type=float, default=1.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = build_flood_recurrence(
        output_root=Path(args.output_root),
        iso3=args.iso3,
        start_year=args.start_year,
        end_year=args.end_year,
        admin_path=Path(args.admin_path),
        admin_layer=args.admin_layer,
        iso3_field=args.iso3_field,
        rivers_path=Path(args.rivers_path),
        lakes_path=Path(args.lakes_path),
        lakes_fallback_path=args.lakes_fallback_path,
        river_min_discharge_cms=args.river_min_discharge_cms,
    )
    print(
        json.dumps(
            {
                "status": "SUCCESS",
                "years": result.years,
                "recurrence_raster": str(result.raster_path),
                "map_png": str(result.map_path),
                "metadata": str(result.metadata_path),
                "pixel_counts": result.pixel_counts,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
