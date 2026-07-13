from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from .flood import close_enough


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str


def _as_path(path_str: str | None) -> Path | None:
    if not path_str:
        return None
    p = Path(path_str)
    return p if p.is_absolute() else Path.cwd() / p


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
        checks.append(CheckResult("run_id_matches_dir", "FAIL", f"run_dir={run_dir.name}, run_id={run_id}"))

    preflight = metadata.get("preflight_coverage", {})
    wp_cov = float((preflight.get("worldpop") or {}).get("coverage_pct", 0.0))
    flood_cov = float((preflight.get("flood_stac") or {}).get("union_bbox_coverage_pct", 0.0))
    thresholds = preflight.get("thresholds") or {}
    wp_thr = float(thresholds.get("worldpop_coverage_min_pct", 98.0))
    flood_thr = float(thresholds.get("flood_stac_union_coverage_min_pct", 99.999))

    if wp_cov >= wp_thr:
        checks.append(CheckResult("preflight_worldpop_threshold", "PASS", f"{wp_cov:.3f} >= {wp_thr:.3f}"))
    else:
        failures += 1
        checks.append(CheckResult("preflight_worldpop_threshold", "FAIL", f"{wp_cov:.3f} < {wp_thr:.3f}"))

    if flood_cov >= flood_thr:
        checks.append(
            CheckResult("preflight_flood_stac_threshold", "PASS", f"{flood_cov:.3f} >= {flood_thr:.3f}")
        )
    else:
        failures += 1
        checks.append(
            CheckResult("preflight_flood_stac_threshold", "FAIL", f"{flood_cov:.3f} < {flood_thr:.3f}")
        )

    table_meta = metadata.get("admin_flood_table") or metadata.get("admin2_flood_table", {})
    table_path = _as_path(table_meta.get("path"))
    if table_path is None or not table_path.exists():
        failures += 1
        checks.append(CheckResult("admin_flood_table_exists", "FAIL", str(table_path)))
        return {
            "run_dir": str(run_dir),
            "metadata_path": str(metadata_path),
            "status": "FAIL",
            "failures": failures,
            "warnings": warnings,
            "checks": [c.__dict__ for c in checks],
        }
    checks.append(CheckResult("admin_flood_table_exists", "PASS", str(table_path)))

    df = pd.read_csv(table_path)
    admin_pcode_col = _find_admin_pcode_col(df)
    required_cols = {"pop_total", "pop_affected_flood", "pct_affected_flood"}
    if admin_pcode_col is None:
        failures += 1
        checks.append(CheckResult("admin_flood_pcode_column", "FAIL", "missing adm{level}_pcode column"))
    else:
        checks.append(CheckResult("admin_flood_pcode_column", "PASS", admin_pcode_col))
    missing = sorted(required_cols - set(df.columns))
    if missing:
        failures += 1
        checks.append(CheckResult("admin_flood_required_columns", "FAIL", ",".join(missing)))
    else:
        checks.append(CheckResult("admin_flood_required_columns", "PASS", "ok"))

    if "pop_total" in df.columns:
        if (df["pop_total"] < -1e-6).any():
            failures += 1
            checks.append(CheckResult("admin_pop_total_non_negative", "FAIL", "negative values"))
        else:
            checks.append(CheckResult("admin_pop_total_non_negative", "PASS", "ok"))

    if "pop_affected_flood" in df.columns:
        if (df["pop_affected_flood"] < -1e-6).any():
            failures += 1
            checks.append(CheckResult("admin_pop_affected_non_negative", "FAIL", "negative values"))
        else:
            checks.append(CheckResult("admin_pop_affected_non_negative", "PASS", "ok"))

    if "pct_affected_flood" in df.columns:
        pct_ok = ((df["pct_affected_flood"] >= -1e-6) & (df["pct_affected_flood"] <= 100.0001)).all()
        if pct_ok:
            checks.append(CheckResult("admin_pct_affected_bounds", "PASS", "0..100"))
        else:
            failures += 1
            checks.append(CheckResult("admin_pct_affected_bounds", "FAIL", "outside 0..100"))

    mask_meta = metadata.get("flood_mask", {})
    days_path = _as_path(mask_meta.get("days_tif"))
    mask_path = _as_path(mask_meta.get("mask_tif"))
    pop_meta = metadata.get("flood_pop_affected", {})
    pop_path = _as_path(pop_meta.get("pop_tif"))
    weighted_path = _as_path(pop_meta.get("pop_weighted_days_tif"))

    for name, path in [
        ("flood_days_raster_exists", days_path),
        ("flood_binary_mask_exists", mask_path),
        ("flood_pop_affected_raster_exists", pop_path),
    ]:
        if path and path.exists():
            checks.append(CheckResult(name, "PASS", str(path)))
        else:
            failures += 1
            checks.append(CheckResult(name, "FAIL", str(path)))

    if weighted_path:
        if weighted_path.exists():
            checks.append(CheckResult("flood_pop_weighted_days_exists", "PASS", str(weighted_path)))
        else:
            warnings += 1
            checks.append(CheckResult("flood_pop_weighted_days_exists", "WARN", str(weighted_path)))

    table_sum = float(df["pop_affected_flood"].sum()) if "pop_affected_flood" in df.columns else float("nan")
    meta_sum = pop_meta.get("pop_affected_sum")
    if meta_sum is not None and table_sum == table_sum:
        meta_sum_f = float(meta_sum)
        if close_enough(table_sum, meta_sum_f, atol=1.0):
            checks.append(
                CheckResult(
                    "table_vs_metadata_pop_affected_sum", "PASS", f"{table_sum:.3f} ~= {meta_sum_f:.3f}"
                )
            )
        else:
            rel_diff = abs(table_sum - meta_sum_f) / max(abs(meta_sum_f), 1.0)
            if rel_diff <= 0.05:
                warnings += 1
                checks.append(
                    CheckResult("table_vs_metadata_pop_affected_sum", "WARN", f"rel_diff={rel_diff:.4%}")
                )
            else:
                failures += 1
                checks.append(
                    CheckResult("table_vs_metadata_pop_affected_sum", "FAIL", f"rel_diff={rel_diff:.4%}")
                )

    missing_artifacts: list[str] = []
    for art in metadata.get("artifacts", []):
        p = _as_path(art.get("path"))
        if p is None or not p.exists():
            missing_artifacts.append(str(p))
    if missing_artifacts:
        warnings += 1
        checks.append(CheckResult("metadata_artifacts_exist", "WARN", f"missing={len(missing_artifacts)}"))
    else:
        checks.append(CheckResult("metadata_artifacts_exist", "PASS", "all_exist"))

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
    lines.append(f"# Flood Parity Report: {Path(report['run_dir']).name}")
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
