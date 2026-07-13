#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from wia_pipelines.batch.execute import run_batch_execution


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Batch pipeline execution runner with retries/resume and heartbeat status.",
    )
    p.add_argument("--readiness-report", default="./outputs/batch/preflight/batch_readiness_report.csv")
    p.add_argument("--preflight-report", default="./outputs/batch/preflight/batch_preflight_report.csv")
    p.add_argument("--admin-path", default="./data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip")
    p.add_argument("--output-root", default="./outputs")
    p.add_argument("--pipeline", action="append", choices=["spei", "utci", "flood", "violence"], default=None)
    p.add_argument("--spei-cmd-template", default=None)
    p.add_argument("--utci-cmd-template", default=None)
    p.add_argument("--flood-cmd-template", default=None)
    p.add_argument("--violence-cmd-template", default=None)
    p.add_argument("--max-retries", type=int, default=2)
    p.add_argument("--stop-on-failure", action=argparse.BooleanOptionalAction, default=False)
    p.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--heartbeat-seconds", type=int, default=30)
    p.add_argument("--step-timeout-minutes", type=int, default=0)
    p.add_argument("--run-cwd", default=".")
    p.add_argument("--out-dir", default="./outputs/batch/run")
    p.add_argument("--dry-run", action="store_true")
    return p


def main() -> int:
    args = build_parser().parse_args()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd_templates = {
        "spei": args.spei_cmd_template,
        "utci": args.utci_cmd_template,
        "flood": args.flood_cmd_template,
        "violence": args.violence_cmd_template,
    }
    cmd_templates = {k: v for k, v in cmd_templates.items() if v is not None}

    out = run_batch_execution(
        readiness=Path(args.readiness_report).resolve(),
        preflight=Path(args.preflight_report).resolve(),
        out_dir=out_dir,
        pipelines=args.pipeline,
        command_templates=cmd_templates,
        admin_path=Path(args.admin_path).resolve(),
        output_root=Path(args.output_root).resolve(),
        max_retries=int(args.max_retries),
        stop_on_failure=bool(args.stop_on_failure),
        resume=bool(args.resume),
        dry_run=bool(args.dry_run),
        heartbeat_seconds=int(args.heartbeat_seconds),
        step_timeout_minutes=int(args.step_timeout_minutes),
        run_cwd=Path(args.run_cwd).resolve() if args.run_cwd else None,
    )
    summary = {
        "report_csv": out["report_csv"],
        "report_json": out["report_json"],
        "status_json": out["status_json"],
        "summary": out["summary"],
    }
    (out_dir / "batch_run_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if int(out["summary"].get("n_failed", 0)) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
