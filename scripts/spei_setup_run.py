#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from wia_pipelines.hazards.spei import (
    SpeiRunInputs,
    build_spei_run_context,
    prepare_spei_geography,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialize SPEI run context and optional geography diagnostics."
    )
    parser.add_argument("--iso3", required=True)
    parser.add_argument("--as-of-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--lookback-months", type=int, default=12)
    parser.add_argument("--output-root", default="./outputs")
    parser.add_argument("--admin-path", required=True)
    parser.add_argument("--admin-layer", default="admin2")
    parser.add_argument("--iso3-field", default="iso3")
    parser.add_argument("--adm-level-field", default=None)
    parser.add_argument("--target-adm-level", type=int, default=2)
    parser.add_argument("--buffer-km", type=float, default=0.0)
    parser.add_argument("--worldpop-path", default=None)
    return parser


def main() -> int:
    args = build_parser().parse_args()

    ctx = build_spei_run_context(
        SpeiRunInputs(
            iso3=args.iso3,
            as_of_date=args.as_of_date,
            lookback_months=args.lookback_months,
            output_root=Path(args.output_root),
            target_adm_level=args.target_adm_level,
            buffer_km=args.buffer_km,
        ),
        create_dirs=True,
        write_metadata=True,
    )

    geo = prepare_spei_geography(
        iso3=args.iso3,
        admin_path=Path(args.admin_path),
        admin_layer=args.admin_layer,
        iso3_field=args.iso3_field,
        adm_level_field=args.adm_level_field,
        target_adm_level=args.target_adm_level,
        buffer_km=args.buffer_km,
        worldpop_path=Path(args.worldpop_path) if args.worldpop_path else None,
    )

    summary = {
        "run_id": ctx["config"].run_id,
        "metadata_path": str(ctx["metadata_path"]),
        "month_window": ctx["month_window"],
        "admin_bounds": geo["aoi"]["admin_bounds"],
        "aoi_bounds": geo["aoi"]["aoi_bounds"],
        "bounds_hash": geo["bounds_hash"],
        "overlap_report": geo["overlap_report"],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
