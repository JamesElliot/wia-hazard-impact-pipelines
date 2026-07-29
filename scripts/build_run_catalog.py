#!/usr/bin/env python3
"""Build a single aggregate CSV catalog of every completed hazard run.

PROD-005: `outputs/*/*/*/run_metadata.json` already records everything needed
to answer "what's been run for country X" -- this just walks that tree once
and emits one row per run instead of requiring anyone to list directories by
hand. Read-only: never modifies anything under output_root.

Older runs (produced before PROD-001 added a terminal `"status": "SUCCESS"`
marker) won't have a `status` field at all -- reported as `UNKNOWN` rather
than assumed complete or incomplete.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def _load_metadata(metadata_path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a corrupt/partial file is reported, not fatal to the scan
        return None


def _first_table_csv(metadata: dict[str, Any]) -> str:
    tables_dir = metadata.get("paths", {}).get("tables")
    if not tables_dir:
        return ""
    candidates = sorted(Path(tables_dir).glob("*.csv")) if Path(tables_dir).is_dir() else []
    return str(candidates[0]) if candidates else ""


# Top-level directories under output_root that are orchestration bookkeeping
# (batch preflight/run reports, shared download caches), not a per-run
# <ISO3>/<WINDOW>/<hazard> directory -- excluded even though a nested
# run_metadata.json under one of these could otherwise match the same
# three-levels-deep glob shape (e.g. outputs/batch/run/logs/run_metadata.json).
_NON_ISO3_TOP_LEVEL_DIRS = {"batch", "_cache", "_migrated_legacy"}


def build_catalog_rows(output_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metadata_path in sorted(output_root.glob("*/*/*/run_metadata.json")):
        # outputs/<ISO3>/<WINDOW>/<hazard>/run_metadata.json
        if metadata_path.parents[2].name in _NON_ISO3_TOP_LEVEL_DIRS:
            continue
        metadata = _load_metadata(metadata_path)
        if metadata is None:
            rows.append(
                {
                    "iso3": metadata_path.parents[2].name,
                    "window": metadata_path.parents[1].name,
                    "hazard": metadata_path.parent.name,
                    "status": "UNREADABLE",
                    "run_id": "",
                    "created_utc": "",
                    "schema_version": "",
                    "method_version": "",
                    "as_of_date": "",
                    "lookback_months": "",
                    "table_csv": "",
                    "run_dir": str(metadata_path.parent),
                }
            )
            continue
        run_config = metadata.get("run_config", {})
        rows.append(
            {
                "iso3": run_config.get("iso3", metadata_path.parents[2].name),
                "window": metadata_path.parents[1].name,
                "hazard": run_config.get("hazard", metadata_path.parent.name),
                "status": metadata.get("status", "UNKNOWN"),
                "run_id": metadata.get("run_id", ""),
                "created_utc": metadata.get("created_utc", ""),
                "schema_version": metadata.get("schema_version", ""),
                "method_version": metadata.get("method_version", ""),
                "as_of_date": run_config.get("as_of_date", ""),
                "lookback_months": run_config.get("lookback_months", ""),
                "table_csv": _first_table_csv(metadata),
                "run_dir": str(metadata_path.parent),
            }
        )
    rows.sort(key=lambda r: (str(r["iso3"]), str(r["hazard"]), str(r["window"])))
    return rows


def write_catalog_csv(rows: list[dict[str, Any]], out_csv: Path) -> None:
    fieldnames = [
        "iso3",
        "hazard",
        "window",
        "status",
        "as_of_date",
        "lookback_months",
        "run_id",
        "created_utc",
        "schema_version",
        "method_version",
        "table_csv",
        "run_dir",
    ]
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Walk outputs/*/*/*/run_metadata.json and emit one aggregate CSV catalog of every run."
    )
    parser.add_argument("--output-root", default="./outputs")
    parser.add_argument("--out-csv", default="./outputs/run_catalog.csv")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    output_root = Path(args.output_root).expanduser().resolve()
    if not output_root.is_dir():
        print(f"Output root does not exist: {output_root}")
        return 1

    rows = build_catalog_rows(output_root)
    out_csv = Path(args.out_csv).expanduser().resolve()
    write_catalog_csv(rows, out_csv)

    n_success = sum(1 for r in rows if r["status"] == "SUCCESS")
    n_unknown = sum(1 for r in rows if r["status"] == "UNKNOWN")
    n_unreadable = sum(1 for r in rows if r["status"] == "UNREADABLE")
    print(f"Wrote {len(rows)} rows to {out_csv}")
    print(f"  SUCCESS={n_success}  UNKNOWN={n_unknown} (pre-status-marker runs)  UNREADABLE={n_unreadable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
