#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from wia_pipelines.batch.readiness import acled_path_for_iso3, worldpop_path_for_iso3
from wia_pipelines.hazards.violence import ViolenceRunInputs, run_violence_pipeline


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run violence pipeline headlessly from Python script.")
    p.add_argument("--iso3", required=True)
    p.add_argument("--as-of-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--lookback-months", type=int, default=12)
    p.add_argument("--target-adm-level", type=int, default=2)
    p.add_argument("--output-root", default="./outputs")
    p.add_argument("--admin-path", default="./data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip")
    p.add_argument("--admin-layer", default=None)
    p.add_argument("--worldpop-path", default=None)
    p.add_argument("--worldpop-dir", default="./data/population")
    p.add_argument("--acled-csv", default=None)
    p.add_argument("--acled-dir", default="./data/violence")
    p.add_argument("--worldpop-coverage-min-pct", type=float, default=98.0)
    p.add_argument("--mask-threshold-events", type=int, default=1)
    p.add_argument("--all-touched", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--included-event-type", action="append", default=None)
    p.add_argument("--dry-run", action="store_true")
    return p


def main() -> int:
    args = build_parser().parse_args()
    iso3 = str(args.iso3).upper()
    admin_layer = args.admin_layer or f"admin{int(args.target_adm_level)}"
    wp_path = (
        Path(args.worldpop_path).expanduser().resolve()
        if args.worldpop_path
        else worldpop_path_for_iso3(iso3, Path(args.worldpop_dir).expanduser().resolve())
    )
    acled_path = (
        Path(args.acled_csv).expanduser().resolve()
        if args.acled_csv
        else acled_path_for_iso3(
            iso3=iso3,
            as_of_date=args.as_of_date,
            lookback_months=int(args.lookback_months),
            acled_dir=Path(args.acled_dir).expanduser().resolve(),
        )
    )

    payload = {
        "pipeline": "violence",
        "iso3": iso3,
        "as_of_date": args.as_of_date,
        "lookback_months": int(args.lookback_months),
        "target_adm_level": int(args.target_adm_level),
        "admin_path": str(Path(args.admin_path).expanduser().resolve()),
        "admin_layer": admin_layer,
        "worldpop_path": str(wp_path),
        "acled_csv": str(acled_path),
        "output_root": str(Path(args.output_root).expanduser().resolve()),
        "worldpop_coverage_min_pct": float(args.worldpop_coverage_min_pct),
        "mask_threshold_events": int(args.mask_threshold_events),
        "all_touched": bool(args.all_touched),
        "included_event_types": args.included_event_type,
    }
    if args.dry_run:
        payload["status"] = "DRY_RUN"
        print(json.dumps(payload, indent=2))
        return 0

    summary = run_violence_pipeline(
        inputs=ViolenceRunInputs(
            iso3=iso3,
            as_of_date=args.as_of_date,
            lookback_months=int(args.lookback_months),
            output_root=Path(args.output_root).expanduser().resolve(),
            target_adm_level=int(args.target_adm_level),
        ),
        admin_path=Path(args.admin_path).expanduser().resolve(),
        worldpop_path=wp_path,
        acled_csv=acled_path,
        admin_layer=admin_layer,
        included_event_types=args.included_event_type,
        worldpop_coverage_min_pct=float(args.worldpop_coverage_min_pct),
        mask_threshold_events=int(args.mask_threshold_events),
        all_touched=bool(args.all_touched),
    )
    payload["status"] = "SUCCESS"
    payload["summary"] = summary
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
