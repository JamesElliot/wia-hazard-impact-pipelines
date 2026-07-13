#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from wia_pipelines.batch.readiness import worldpop_path_for_iso3
from wia_pipelines.hazards.flood import (
    FloodPipelineRunOptions,
    FloodRunInputs,
    run_flood_pipeline,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run flood pipeline headlessly from Python script.")
    p.add_argument("--iso3", required=True)
    p.add_argument("--as-of-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--lookback-months", type=int, default=12)
    p.add_argument("--target-adm-level", type=int, default=2)
    p.add_argument("--output-root", default="./outputs")
    p.add_argument("--admin-path", default="./data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip")
    p.add_argument("--admin-layer", default=None)
    p.add_argument("--iso3-field", default="iso3")
    p.add_argument("--worldpop-path", default=None)
    p.add_argument("--worldpop-dir", default="./data/population")
    p.add_argument("--stac-api-url", default="https://stac.eodc.eu/api/v1")
    p.add_argument("--collection-id", default="GFM")
    p.add_argument("--asset-key", default="ensemble_flood_extent")
    p.add_argument("--datetime-range", default=None, help="STAC datetime range. Defaults to run window.")
    p.add_argument("--worldpop-coverage-min-pct", type=float, default=98.0)
    p.add_argument("--flood-stac-coverage-min-pct", type=float, default=99.999)
    p.add_argument("--flood-stac-coverage-hard-min-pct", type=float, default=50.0)
    p.add_argument("--flood-binary-threshold-days", type=int, default=0)
    p.add_argument("--chunk-y", type=int, default=1024)
    p.add_argument("--chunk-x", type=int, default=1024)
    p.add_argument("--dry-run", action="store_true")
    return p


def main() -> int:
    args = build_parser().parse_args()
    iso3 = str(args.iso3).upper()
    worldpop_path = (
        Path(args.worldpop_path).expanduser().resolve()
        if args.worldpop_path
        else worldpop_path_for_iso3(iso3, Path(args.worldpop_dir).expanduser().resolve())
    )
    payload = {
        "pipeline": "flood",
        "iso3": iso3,
        "as_of_date": args.as_of_date,
        "lookback_months": int(args.lookback_months),
        "target_adm_level": int(args.target_adm_level),
        "admin_path": str(Path(args.admin_path).expanduser().resolve()),
        "admin_layer": args.admin_layer or f"admin{int(args.target_adm_level)}",
        "worldpop_path": str(worldpop_path),
        "output_root": str(Path(args.output_root).expanduser().resolve()),
        "stac_api_url": args.stac_api_url,
        "collection_id": args.collection_id,
        "asset_key": args.asset_key,
        "datetime_range": args.datetime_range,
        "worldpop_coverage_min_pct": float(args.worldpop_coverage_min_pct),
        "flood_stac_coverage_min_pct": float(args.flood_stac_coverage_min_pct),
        "flood_stac_coverage_hard_min_pct": float(args.flood_stac_coverage_hard_min_pct),
        "flood_binary_threshold_days": int(args.flood_binary_threshold_days),
        "chunk_y": int(args.chunk_y),
        "chunk_x": int(args.chunk_x),
    }
    if args.dry_run:
        payload["status"] = "DRY_RUN"
        print(json.dumps(payload, indent=2))
        return 0

    out = run_flood_pipeline(
        FloodPipelineRunOptions(
            inputs=FloodRunInputs(
                iso3=iso3,
                as_of_date=args.as_of_date,
                lookback_months=int(args.lookback_months),
                output_root=Path(args.output_root).expanduser().resolve(),
                target_adm_level=int(args.target_adm_level),
            ),
            admin_path=Path(args.admin_path).expanduser().resolve(),
            worldpop_path=worldpop_path,
            admin_layer=args.admin_layer or f"admin{int(args.target_adm_level)}",
            iso3_field=args.iso3_field,
            stac_api_url=args.stac_api_url,
            collection_id=args.collection_id,
            asset_key=args.asset_key,
            datetime_range=args.datetime_range,
            worldpop_coverage_min_pct=float(args.worldpop_coverage_min_pct),
            flood_stac_coverage_min_pct=float(args.flood_stac_coverage_min_pct),
            flood_stac_coverage_hard_min_pct=float(args.flood_stac_coverage_hard_min_pct),
            flood_binary_threshold_days=int(args.flood_binary_threshold_days),
            chunk_y=int(args.chunk_y),
            chunk_x=int(args.chunk_x),
        )
    )
    payload["status"] = "SUCCESS"
    payload["summary"] = out
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
