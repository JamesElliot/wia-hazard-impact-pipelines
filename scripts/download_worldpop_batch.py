#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from wia_pipelines.batch.manifest import load_batch_manifest
from wia_pipelines.batch.worldpop_download import (
    build_worldpop_download_plan,
    download_worldpop_specs,
    write_download_report,
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Download missing WorldPop files for countries in batch manifest."
    )
    p.add_argument("--manifest", default="./data/batch_tasks.csv")
    p.add_argument("--iso-lookup-path", default="./data/violence/iso_country-codes.csv")
    p.add_argument("--default-admin-level", type=int, default=2)
    p.add_argument("--worldpop-dir", default="./data/population")
    p.add_argument("--year", type=int, default=2025)
    p.add_argument("--release", default="R2025A")
    p.add_argument("--version", default="v1")
    p.add_argument("--resolution", default="100m")
    p.add_argument("--constrained-folder", default="constrained")
    p.add_argument("--base-url", default="https://data.worldpop.org/GIS/Population/Global_2015_2030")
    p.add_argument("--out-dir", default="./outputs/batch/worldpop_download")
    p.add_argument("--timeout-seconds", type=int, default=120)
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p


def main() -> int:
    args = build_parser().parse_args()

    tasks = load_batch_manifest(
        manifest_path=Path(args.manifest).resolve(),
        default_admin_level=args.default_admin_level,
        iso_lookup_path=Path(args.iso_lookup_path).resolve(),
    )
    specs = build_worldpop_download_plan(
        tasks=tasks,
        worldpop_dir=Path(args.worldpop_dir).resolve(),
        year=args.year,
        release=args.release,
        version=args.version,
        resolution=args.resolution,
        constrained_folder=args.constrained_folder,
        base_url=args.base_url,
    )

    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "DRY_RUN",
                    "n_specs": len(specs),
                    "worldpop_dir": str(Path(args.worldpop_dir).resolve()),
                    "specs_preview": [
                        {"iso3": s.iso3, "url": s.url, "output_path": str(s.output_path)}
                        for s in specs[: min(10, len(specs))]
                    ],
                },
                indent=2,
            )
        )
        return 0

    report = download_worldpop_specs(
        specs=specs,
        force=bool(args.force),
        timeout_seconds=int(args.timeout_seconds),
    )
    outputs = write_download_report(report=report, out_dir=Path(args.out_dir).resolve())

    summary = {
        "n_total": int(len(report)),
        "n_downloaded": int((report["status"] == "DOWNLOADED").sum()) if not report.empty else 0,
        "n_exists": int((report["status"] == "EXISTS").sum()) if not report.empty else 0,
        "n_failed": int((report["status"] == "FAILED").sum()) if not report.empty else 0,
        **outputs,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
