#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from wia_pipelines.batch.issues import write_issue_report
from wia_pipelines.batch.manifest import load_batch_manifest
from wia_pipelines.batch.preflight import run_batch_preflight
from wia_pipelines.batch.readiness import evaluate_batch_readiness


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Batch manifest normalization + readiness checks + multi-hazard preflight coverage checks."
    )
    p.add_argument("--manifest", default="./data/batch_tasks.csv")
    p.add_argument("--iso-lookup-path", default="./data/violence/iso_country-codes.csv")
    p.add_argument("--admin-path", default="./data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip")
    p.add_argument("--worldpop-dir", default="./data/population")
    p.add_argument("--acled-dir", default="./data/violence")
    p.add_argument("--acled-bulk-path", default="./data/violence/acled_all_20250101-20251231.csv")
    p.add_argument(
        "--build-country-acled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Create country ACLED files from bulk export when missing.",
    )
    p.add_argument("--acled-bulk-iso-column", default="iso")
    p.add_argument("--default-admin-level", type=int, default=2)
    p.add_argument("--sample-year", type=int, default=2025)
    p.add_argument("--sample-month", type=int, default=1)
    p.add_argument("--cds-buffer-deg", type=float, default=0.25)
    p.add_argument("--flood-datetime", default="2025-01-01/2025-01-31")
    p.add_argument("--flood-mode", choices=["extents", "asset"], default="extents")
    p.add_argument("--out-dir", default="./outputs/batch/preflight")
    return p


def main() -> int:
    args = build_parser().parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = load_batch_manifest(
        manifest_path=Path(args.manifest).resolve(),
        default_admin_level=args.default_admin_level,
        iso_lookup_path=Path(args.iso_lookup_path).resolve(),
    )
    normalized_path = out_dir / "batch_manifest_normalized.csv"
    tasks.to_csv(normalized_path, index=False)

    readiness = evaluate_batch_readiness(
        tasks=tasks,
        admin_path=Path(args.admin_path).resolve(),
        worldpop_dir=Path(args.worldpop_dir).resolve(),
        acled_dir=Path(args.acled_dir).resolve(),
        bulk_acled_path=None if args.acled_bulk_path is None else Path(args.acled_bulk_path).resolve(),
        create_country_acled_from_bulk=bool(args.build_country_acled),
        bulk_acled_iso_column=args.acled_bulk_iso_column,
    )
    readiness_path = out_dir / "batch_readiness_report.csv"
    readiness.to_csv(readiness_path, index=False)

    preflight = run_batch_preflight(
        readiness=readiness,
        admin_path=Path(args.admin_path).resolve(),
        sample_year=args.sample_year,
        sample_month=args.sample_month,
        cds_buffer_deg=args.cds_buffer_deg,
        flood_datetime=args.flood_datetime,
        flood_mode=args.flood_mode,
        out_dir=out_dir,
    )
    issue_outputs = write_issue_report(
        readiness=readiness,
        preflight=preflight["report"],
        out_dir=out_dir,
    )

    summary = {
        "normalized_manifest": str(normalized_path),
        "readiness_report": str(readiness_path),
        "preflight_report_csv": preflight["report_csv"],
        "preflight_report_json": preflight["report_json"],
        "preflight_status_json": preflight["status_json"],
        **issue_outputs,
        "summary": preflight["summary"],
    }
    summary_path = out_dir / "batch_preflight_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
