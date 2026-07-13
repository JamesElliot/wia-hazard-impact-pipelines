from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str


def _close(a: float, b: float, atol: float = 1e-3, rtol: float = 1e-7) -> bool:
    return math.isclose(a, b, abs_tol=atol, rel_tol=rtol)


def _artifact_path(metadata: dict[str, Any], kind: str) -> Path | None:
    for art in metadata.get("artifacts", []):
        if art.get("kind") == kind:
            p = Path(art.get("path", ""))
            return p if p.is_absolute() else Path.cwd() / p
    return None


def _find_admin_pcode_col(df: pd.DataFrame) -> str | None:
    for col in df.columns:
        if re.fullmatch(r"adm\d+_pcode", str(col).lower()):
            return str(col)
    return None


def run_checks(run_dir: Path) -> dict[str, Any]:
    checks: list[CheckResult] = []
    failures = 0
    warnings = 0

    metadata_path = run_dir / "run_metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"Missing run metadata: {metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    run_id = metadata.get("run_id")
    if run_id and run_dir.name == run_id:
        checks.append(CheckResult("run_id_matches_dir", "PASS", run_id))
    else:
        failures += 1
        checks.append(
            CheckResult(
                "run_id_matches_dir",
                "FAIL",
                f"run_dir={run_dir.name}, run_id={run_id}",
            )
        )

    preflight = metadata.get("preflight_coverage", {})
    utci_cov = preflight.get("utci_sample", {})
    if utci_cov.get("full_coverage") is True:
        checks.append(CheckResult("preflight_utci_full_coverage", "PASS", "true"))
    else:
        failures += 1
        checks.append(
            CheckResult(
                "preflight_utci_full_coverage",
                "FAIL",
                f"value={utci_cov.get('full_coverage')}",
            )
        )

    wp_cov = preflight.get("worldpop", {})
    if wp_cov.get("full_coverage") is True:
        checks.append(CheckResult("preflight_worldpop_full_coverage", "PASS", "true"))
    else:
        warnings += 1
        checks.append(
            CheckResult(
                "preflight_worldpop_full_coverage",
                "WARN",
                f"value={wp_cov.get('full_coverage')}, pct={wp_cov.get('coverage_pct')}",
            )
        )

    admin_table = metadata.get("admin_table") or metadata.get("admin2_table", {})
    table_path = Path(admin_table.get("path", ""))
    if not table_path.is_absolute():
        table_path = Path.cwd() / table_path
    if not table_path.exists():
        failures += 1
        checks.append(CheckResult("admin_table_exists", "FAIL", str(table_path)))
        return {
            "run_dir": str(run_dir),
            "metadata_path": str(metadata_path),
            "status": "FAIL",
            "failures": failures,
            "warnings": warnings,
            "checks": [c.__dict__ for c in checks],
        }
    checks.append(CheckResult("admin_table_exists", "PASS", str(table_path)))

    df = pd.read_csv(table_path)
    pcode_col = _find_admin_pcode_col(df)
    if pcode_col and "pop_total" in df.columns:
        checks.append(CheckResult("admin_table_required_columns", "PASS", f"ok ({pcode_col})"))
    else:
        failures += 1
        checks.append(
            CheckResult("admin_table_required_columns", "FAIL", "missing adm{level}_pcode/pop_total")
        )

    if (df.get("pop_total", pd.Series(dtype=float)) < 0).any():
        failures += 1
        checks.append(CheckResult("admin_pop_total_non_negative", "FAIL", "negative pop_total"))
    else:
        checks.append(CheckResult("admin_pop_total_non_negative", "PASS", "ok"))

    thresholds = admin_table.get("thresholds") or {}
    if not thresholds:
        failures += 1
        checks.append(CheckResult("thresholds_available", "FAIL", "none in metadata.admin_table.thresholds"))
    else:
        checks.append(CheckResult("thresholds_available", "PASS", f"n={len(thresholds)}"))

    qc_json = _artifact_path(metadata, "qc_admin_table_json") or _artifact_path(
        metadata, "qc_admin2_table_json"
    )
    qc_payload: dict[str, Any] = {}
    if qc_json and qc_json.exists():
        qc_payload = json.loads(qc_json.read_text(encoding="utf-8"))
        checks.append(CheckResult("qc_admin_json_exists", "PASS", str(qc_json)))
    else:
        warnings += 1
        checks.append(
            CheckResult("qc_admin_json_exists", "WARN", str(qc_json) if qc_json else "not recorded")
        )

    mask_summary = (metadata.get("extreme_heat_masks") or {}).get("results_summary") or {}
    for key in thresholds.keys():
        pop_col = f"pop_exposed_{key}"
        pct_col = f"pct_exposed_{key}"
        if pop_col not in df.columns or pct_col not in df.columns:
            failures += 1
            checks.append(CheckResult(f"{key}_table_columns", "FAIL", f"missing {pop_col}/{pct_col}"))
            continue
        checks.append(CheckResult(f"{key}_table_columns", "PASS", "ok"))

        if (df[pop_col] < -1e-6).any():
            failures += 1
            checks.append(CheckResult(f"{key}_table_pop_non_negative", "FAIL", "negative values"))
        else:
            checks.append(CheckResult(f"{key}_table_pop_non_negative", "PASS", "ok"))

        pct_ok = ((df[pct_col] >= -1e-6) & (df[pct_col] <= 100.0001)).all()
        if pct_ok:
            checks.append(CheckResult(f"{key}_pct_bounds", "PASS", "0..100"))
        else:
            failures += 1
            checks.append(CheckResult(f"{key}_pct_bounds", "FAIL", "outside 0..100"))

        table_sum = float(df[pop_col].sum())

        # Compare against mask summary population (country-level raster sum before admin allocation).
        if key in mask_summary and "pop_affected" in mask_summary[key]:
            meta_sum = float(mask_summary[key]["pop_affected"])
            rel_diff = abs(table_sum - meta_sum) / max(abs(meta_sum), 1.0)
            if _close(table_sum, meta_sum, atol=1e-2):
                checks.append(
                    CheckResult(f"{key}_table_vs_metadata_sum", "PASS", f"{table_sum:.3f} ~= {meta_sum:.3f}")
                )
            elif rel_diff <= 0.005:
                warnings += 1
                checks.append(CheckResult(f"{key}_table_vs_metadata_sum", "WARN", f"rel_diff={rel_diff:.4%}"))
            else:
                failures += 1
                checks.append(CheckResult(f"{key}_table_vs_metadata_sum", "FAIL", f"rel_diff={rel_diff:.4%}"))

        # Compare against QC raster summary if available.
        rc = (qc_payload.get("raster_checks") or {}).get(key)
        if rc and rc.get("exists") and rc.get("sum_exposed_pop") is not None:
            qc_sum = float(rc["sum_exposed_pop"])
            rel_diff = abs(table_sum - qc_sum) / max(abs(qc_sum), 1.0)
            if _close(table_sum, qc_sum, atol=1e-2):
                checks.append(
                    CheckResult(f"{key}_table_vs_qc_raster_sum", "PASS", f"{table_sum:.3f} ~= {qc_sum:.3f}")
                )
            elif rel_diff <= 0.005:
                warnings += 1
                checks.append(
                    CheckResult(f"{key}_table_vs_qc_raster_sum", "WARN", f"rel_diff={rel_diff:.4%}")
                )
            else:
                failures += 1
                checks.append(
                    CheckResult(f"{key}_table_vs_qc_raster_sum", "FAIL", f"rel_diff={rel_diff:.4%}")
                )

    # Absolute-threshold monotonicity if all are present.
    abs_keys = [k for k in ("abs_32c", "abs_38c", "abs_46c") if f"pop_exposed_{k}" in df.columns]
    for i in range(len(abs_keys) - 1):
        a = abs_keys[i]
        b = abs_keys[i + 1]
        if (df[f"pop_exposed_{a}"] + 1e-6 >= df[f"pop_exposed_{b}"]).all():
            checks.append(CheckResult(f"monotonic_{a}_ge_{b}", "PASS", "ok"))
        else:
            failures += 1
            checks.append(CheckResult(f"monotonic_{a}_ge_{b}", "FAIL", "violations found"))

    qc_report = metadata.get("qc_report", {}).get("path")
    if qc_report:
        qcp = Path(qc_report)
        if not qcp.is_absolute():
            qcp = Path.cwd() / qcp
        if qcp.exists():
            checks.append(CheckResult("qc_report_exists", "PASS", str(qcp)))
        else:
            warnings += 1
            checks.append(CheckResult("qc_report_exists", "WARN", str(qcp)))

    status = "PASS" if failures == 0 else "FAIL"
    return {
        "run_dir": str(run_dir),
        "metadata_path": str(metadata_path),
        "status": status,
        "failures": failures,
        "warnings": warnings,
        "checks": [c.__dict__ for c in checks],
    }


def to_markdown(report: dict[str, Any]) -> str:
    lines = []
    lines.append(f"# UTCI Parity Report: {Path(report['run_dir']).name}")
    lines.append("")
    lines.append(f"- Status: **{report['status']}**")
    lines.append(f"- Failures: {report['failures']}")
    lines.append(f"- Warnings: {report['warnings']}")
    lines.append("")
    lines.append("| Check | Status | Detail |")
    lines.append("|---|---|---|")
    for c in report["checks"]:
        detail = str(c["detail"]).replace("|", "\\|")
        lines.append(f"| `{c['name']}` | {c['status']} | {detail} |")
    lines.append("")
    return "\n".join(lines)
