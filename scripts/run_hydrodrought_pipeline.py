#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from wia_pipelines.core.assets import resolve_admin_path
from wia_pipelines.batch.readiness import worldpop_path_for_iso3
from wia_pipelines.core.assets import resolve_hydrorivers_path
from wia_pipelines.hazards.hydrodrought import (
    HydrodroughtPipelineRunOptions,
    HydrodroughtRunInputs,
    run_hydrodrought_pipeline,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run hydrological drought (GloFAS/SRI) pipeline headlessly.")
    p.add_argument("--iso3", required=True)
    p.add_argument("--as-of-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--lookback-months", type=int, default=12)
    p.add_argument("--target-adm-level", type=int, default=2)
    p.add_argument("--output-root", default="./outputs")
    p.add_argument(
        "--admin-path",
        default=None,
        help=(
            "Admin boundary asset. Defaults to a per-country COD-AB override "
            "registered under data/cod-ab/*/admin_source.json when one exists "
            "for --iso3, else data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip."
        ),
    )
    p.add_argument("--admin-layer", default=None)
    p.add_argument("--iso3-field", default="iso3")
    p.add_argument("--worldpop-path", default=None)
    p.add_argument("--worldpop-dir", default="./data/population")
    p.add_argument("--hydrorivers-path", default=None)
    p.add_argument("--cds-buffer-deg", type=float, default=0.25)
    p.add_argument("--accumulation-months", type=int, default=3)
    p.add_argument("--baseline-start-year", type=int, default=1991)
    p.add_argument("--baseline-end-year", type=int, default=2020)
    p.add_argument("--corridor-base-width-km", type=float, default=5.0)
    p.add_argument("--corridor-per-order-km", type=float, default=0.0)
    p.add_argument("--default-threshold-key", default="rel_sri_le_m1p5_p2m")
    p.add_argument("--allow-partial-preflight", action="store_true")
    p.add_argument("--ewds-url", default=None)
    p.add_argument("--ewds-key", default=None)
    p.add_argument("--dry-run", action="store_true")
    return p


def main() -> int:
    args = build_parser().parse_args()
    iso3 = str(args.iso3).upper()
    admin_path = resolve_admin_path(args.admin_path, iso3=iso3)
    worldpop_path = (
        Path(args.worldpop_path).expanduser().resolve()
        if args.worldpop_path
        else worldpop_path_for_iso3(iso3, Path(args.worldpop_dir).expanduser().resolve())
    )
    hydrorivers_path = resolve_hydrorivers_path(args.hydrorivers_path)
    payload = {
        "pipeline": "hydrodrought",
        "iso3": iso3,
        "as_of_date": args.as_of_date,
        "lookback_months": int(args.lookback_months),
        "target_adm_level": int(args.target_adm_level),
        "admin_path": str(admin_path),
        "admin_layer": args.admin_layer or f"admin{int(args.target_adm_level)}",
        "worldpop_path": str(worldpop_path),
        "hydrorivers_path": str(hydrorivers_path),
        "output_root": str(Path(args.output_root).expanduser().resolve()),
        "cds_buffer_deg": float(args.cds_buffer_deg),
        "accumulation_months": int(args.accumulation_months),
        "baseline_start_year": int(args.baseline_start_year),
        "baseline_end_year": int(args.baseline_end_year),
        "corridor_base_width_km": float(args.corridor_base_width_km),
        "corridor_per_order_km": float(args.corridor_per_order_km),
        "default_threshold_key": args.default_threshold_key,
        "require_full_preflight_coverage": not bool(args.allow_partial_preflight),
    }
    if args.dry_run:
        payload["status"] = "DRY_RUN"
        print(json.dumps(payload, indent=2))
        return 0

    out = run_hydrodrought_pipeline(
        HydrodroughtPipelineRunOptions(
            inputs=HydrodroughtRunInputs(
                iso3=iso3,
                as_of_date=args.as_of_date,
                lookback_months=int(args.lookback_months),
                output_root=Path(args.output_root).expanduser().resolve(),
                target_adm_level=int(args.target_adm_level),
            ),
            admin_path=admin_path,
            worldpop_path=worldpop_path,
            hydrorivers_path=hydrorivers_path,
            admin_layer=args.admin_layer or f"admin{int(args.target_adm_level)}",
            iso3_field=args.iso3_field,
            cds_buffer_deg=float(args.cds_buffer_deg),
            accumulation_months=int(args.accumulation_months),
            baseline_start_year=int(args.baseline_start_year),
            baseline_end_year=int(args.baseline_end_year),
            corridor_base_width_km=float(args.corridor_base_width_km),
            corridor_per_order_km=float(args.corridor_per_order_km),
            default_threshold_key=args.default_threshold_key,
            require_full_preflight_coverage=not bool(args.allow_partial_preflight),
            ewds_url=args.ewds_url,
            ewds_key=args.ewds_key,
        )
    )
    payload["status"] = "SUCCESS"
    payload["summary"] = out
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
