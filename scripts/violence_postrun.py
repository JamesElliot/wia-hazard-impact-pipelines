#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from wia_pipelines.config import validate_run_metadata
from wia_pipelines.hazards.violence_parity import run_checks, to_markdown


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run standardized violence post-run checks (schema + parity).")
    p.add_argument("--run-dir", required=True, help="Path to violence run directory.")
    p.add_argument("--skip-metadata-validation", action="store_true")
    p.add_argument("--strict-metadata-validation", action="store_true")
    p.add_argument("--skip-parity", action="store_true")
    return p


def main() -> int:
    args = build_parser().parse_args()
    run_dir = Path(args.run_dir).resolve()
    metadata_path = run_dir / "run_metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"Missing run metadata: {metadata_path}")

    failures = 0
    warnings = 0
    outputs: dict[str, str] = {}

    if not args.skip_metadata_validation:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        try:
            validate_run_metadata(payload)
            outputs["metadata_validation"] = "passed"
        except Exception as exc:
            warnings += 1
            outputs["metadata_validation"] = f"warning: {exc.__class__.__name__}"
            outputs["metadata_validation_note"] = str(exc).splitlines()[0]
            if args.strict_metadata_validation:
                failures += 1

    if not args.skip_parity:
        report = run_checks(run_dir)
        out_json = run_dir / "qc" / "violence" / "violence_parity_report.json"
        out_md = run_dir / "qc" / "violence" / "violence_parity_report.md"
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        out_md.write_text(to_markdown(report), encoding="utf-8")
        outputs["parity_json"] = str(out_json)
        outputs["parity_md"] = str(out_md)
        failures += int(report["failures"])
        warnings += int(report["warnings"])

    status = "PASS" if failures == 0 else "FAIL"
    print(
        json.dumps(
            {
                "status": status,
                "failures": failures,
                "warnings": warnings,
                "run_dir": str(run_dir),
                "outputs": outputs,
            },
            indent=2,
        )
    )
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
