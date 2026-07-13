#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from wia_pipelines.batch.readiness import worldpop_path_for_iso3
from wia_pipelines.hazards.utci import (
    UtciPipelineRunOptions,
    UtciRunInputs,
    run_utci_pipeline,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run UTCI pipeline headlessly from Python script.")
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
    p.add_argument("--cds-buffer-deg", type=float, default=0.25)
    p.add_argument("--k-consecutive-days", type=int, default=3)
    p.add_argument(
        "--abs-threshold-c",
        action="append",
        type=float,
        default=None,
        help="Repeat to set absolute UTCI thresholds in C (default: 32,38,46).",
    )
    p.add_argument("--allow-partial-preflight", action="store_true")
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
    thresholds = tuple(args.abs_threshold_c) if args.abs_threshold_c else (32.0, 38.0, 46.0)
    payload = {
        "pipeline": "utci",
        "iso3": iso3,
        "as_of_date": args.as_of_date,
        "lookback_months": int(args.lookback_months),
        "target_adm_level": int(args.target_adm_level),
        "admin_path": str(Path(args.admin_path).expanduser().resolve()),
        "admin_layer": args.admin_layer or f"admin{int(args.target_adm_level)}",
        "worldpop_path": str(worldpop_path),
        "output_root": str(Path(args.output_root).expanduser().resolve()),
        "cds_buffer_deg": float(args.cds_buffer_deg),
        "k_consecutive_days": int(args.k_consecutive_days),
        "abs_thresholds_c": [float(v) for v in thresholds],
        "require_full_preflight_coverage": not bool(args.allow_partial_preflight),
    }
    if args.dry_run:
        payload["status"] = "DRY_RUN"
        print(json.dumps(payload, indent=2))
        return 0

    out = run_utci_pipeline(
        UtciPipelineRunOptions(
            inputs=UtciRunInputs(
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
            cds_buffer_deg=float(args.cds_buffer_deg),
            abs_thresholds_c=tuple(float(v) for v in thresholds),
            k_consecutive_days=int(args.k_consecutive_days),
            require_full_preflight_coverage=not bool(args.allow_partial_preflight),
        )
    )
    payload["status"] = "SUCCESS"
    payload["summary"] = out
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
