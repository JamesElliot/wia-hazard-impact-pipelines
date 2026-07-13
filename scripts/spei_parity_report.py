#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from wia_pipelines.hazards.spei_parity import run_checks, to_markdown


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Validate SPEI run parity between metadata, files, tables, and rasters."
    )
    p.add_argument("--run-dir", required=True, help="Path to SPEI run directory.")
    p.add_argument(
        "--out-json",
        default=None,
        help="Optional output JSON path. Defaults to <run-dir>/qc/spei/spei_parity_report.json.",
    )
    p.add_argument(
        "--out-md",
        default=None,
        help="Optional output markdown path. Defaults to <run-dir>/qc/spei/spei_parity_report.md.",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    run_dir = Path(args.run_dir).resolve()
    report = run_checks(run_dir)

    out_json = (
        Path(args.out_json).resolve()
        if args.out_json
        else run_dir / "qc" / "spei" / "spei_parity_report.json"
    )
    out_md = Path(args.out_md).resolve() if args.out_md else run_dir / "qc" / "spei" / "spei_parity_report.md"

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    out_md.write_text(to_markdown(report), encoding="utf-8")

    print(
        json.dumps(
            {
                "status": report["status"],
                "failures": report["failures"],
                "warnings": report["warnings"],
                "out_json": str(out_json),
                "out_md": str(out_md),
            },
            indent=2,
        )
    )
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
