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


def _as_path(path_str: str | None) -> Path | None:
    if not path_str:
        return None
    p = Path(path_str)
    return p if p.is_absolute() else Path.cwd() / p


def _close(a: float, b: float, atol: float = 1e-3, rtol: float = 1e-7) -> bool:
    return math.isclose(a, b, abs_tol=atol, rel_tol=rtol)


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
    wp = preflight.get("worldpop", {})
    wp_cov = float(wp.get("coverage_pct", 0.0))
    wp_thr = float((preflight.get("thresholds") or {}).get("worldpop_coverage_min_pct", 98.0))
    if wp_cov >= wp_thr:
        checks.append(CheckResult("preflight_worldpop_threshold", "PASS", f"{wp_cov:.3f} >= {wp_thr:.3f}"))
    else:
        failures += 1
        checks.append(CheckResult("preflight_worldpop_threshold", "FAIL", f"{wp_cov:.3f} < {wp_thr:.3f}"))

    acled = preflight.get("acled_events", {})
    n_events = int(acled.get("n_events_after_filters", -1))
    if n_events >= 1:
        checks.append(CheckResult("preflight_acled_events_nonempty", "PASS", str(n_events)))
    else:
        failures += 1
        checks.append(CheckResult("preflight_acled_events_nonempty", "FAIL", str(n_events)))

    table_meta = metadata.get("admin_stats") or metadata.get("adm2_stats", {})
    table_path = _as_path(table_meta.get("admin_stats_csv") or table_meta.get("adm2_stats_csv"))
    if table_path is None or not table_path.exists():
        failures += 1
        checks.append(CheckResult("admin_stats_csv_exists", "FAIL", str(table_path)))
        return {
            "run_dir": str(run_dir),
            "metadata_path": str(metadata_path),
            "status": "FAIL",
            "failures": failures,
            "warnings": warnings,
            "checks": [c.__dict__ for c in checks],
        }
    checks.append(CheckResult("admin_stats_csv_exists", "PASS", str(table_path)))

    df = pd.read_csv(table_path)
    pcode_col = _find_admin_pcode_col(df)
    required_cols = {
        "pop_total",
        "pop_affected",
        "pct_affected",
        "pop_weighted_event_count_sum",
        "pop_weighted_mean_event_count",
    }
    if pcode_col is None:
        failures += 1
        checks.append(CheckResult("admin_pcode_column", "FAIL", "missing adm{level}_pcode column"))
    else:
        checks.append(CheckResult("admin_pcode_column", "PASS", pcode_col))
    missing = sorted(required_cols - set(df.columns))
    if missing:
        failures += 1
        checks.append(CheckResult("admin_required_columns", "FAIL", ",".join(missing)))
    else:
        checks.append(CheckResult("admin_required_columns", "PASS", "ok"))

    if "pop_total" in df.columns:
        if (df["pop_total"] < -1e-6).any():
            failures += 1
            checks.append(CheckResult("admin_pop_total_non_negative", "FAIL", "negative values"))
        else:
            checks.append(CheckResult("admin_pop_total_non_negative", "PASS", "ok"))
    if "pop_affected" in df.columns:
        if (df["pop_affected"] < -1e-6).any():
            failures += 1
            checks.append(CheckResult("admin_pop_affected_non_negative", "FAIL", "negative values"))
        else:
            checks.append(CheckResult("admin_pop_affected_non_negative", "PASS", "ok"))
    if "pct_affected" in df.columns:
        pct_ok = ((df["pct_affected"] >= -1e-6) & (df["pct_affected"] <= 100.0001)).all()
        if pct_ok:
            checks.append(CheckResult("admin_pct_bounds", "PASS", "0..100"))
        else:
            failures += 1
            checks.append(CheckResult("admin_pct_bounds", "FAIL", "outside 0..100"))
    if "pop_weighted_event_count_sum" in df.columns:
        if (df["pop_weighted_event_count_sum"] < -1e-6).any():
            failures += 1
            checks.append(
                CheckResult("admin_pop_weighted_event_count_sum_non_negative", "FAIL", "negative values")
            )
        else:
            checks.append(CheckResult("admin_pop_weighted_event_count_sum_non_negative", "PASS", "ok"))
    if "pop_weighted_mean_event_count" in df.columns:
        if (df["pop_weighted_mean_event_count"] < -1e-6).any():
            failures += 1
            checks.append(
                CheckResult("admin_pop_weighted_mean_event_count_non_negative", "FAIL", "negative values")
            )
        else:
            checks.append(CheckResult("admin_pop_weighted_mean_event_count_non_negative", "PASS", "ok"))

    pop_meta = metadata.get("population_impact", {})
    affected_raster = _as_path(pop_meta.get("affected_pop_tif"))
    weighted_count_raster = _as_path(pop_meta.get("pop_weighted_event_count_tif"))
    intensity_raster = _as_path((metadata.get("hazard_intensity") or {}).get("event_count_tif"))
    mask_raster = _as_path((metadata.get("hazard_mask") or {}).get("mask_tif"))
    if affected_raster and affected_raster.exists():
        checks.append(CheckResult("pop_affected_raster_exists", "PASS", str(affected_raster)))
    else:
        failures += 1
        checks.append(CheckResult("pop_affected_raster_exists", "FAIL", str(affected_raster)))
    if mask_raster and mask_raster.exists():
        checks.append(CheckResult("hazard_mask_raster_exists", "PASS", str(mask_raster)))
    else:
        failures += 1
        checks.append(CheckResult("hazard_mask_raster_exists", "FAIL", str(mask_raster)))
    if weighted_count_raster and weighted_count_raster.exists():
        checks.append(
            CheckResult("pop_weighted_event_count_raster_exists", "PASS", str(weighted_count_raster))
        )
    else:
        failures += 1
        checks.append(
            CheckResult("pop_weighted_event_count_raster_exists", "FAIL", str(weighted_count_raster))
        )
    if intensity_raster and intensity_raster.exists():
        checks.append(CheckResult("event_count_raster_exists", "PASS", str(intensity_raster)))
    else:
        failures += 1
        checks.append(CheckResult("event_count_raster_exists", "FAIL", str(intensity_raster)))

    hazard_mask_meta = metadata.get("hazard_mask", {})
    threshold_metric = hazard_mask_meta.get("threshold_metric")
    threshold_value = hazard_mask_meta.get("threshold_value")
    if threshold_metric == "event_count" and threshold_value is not None and float(threshold_value) >= 1:
        checks.append(
            CheckResult("hazard_mask_threshold_metadata", "PASS", f"{threshold_metric}>={threshold_value}")
        )
    else:
        warnings += 1
        checks.append(
            CheckResult(
                "hazard_mask_threshold_metadata",
                "WARN",
                f"metric={threshold_metric}, value={threshold_value}",
            )
        )

    if "affected_population" in pop_meta and "pop_affected" in df.columns:
        table_sum = float(df["pop_affected"].sum())
        meta_sum = float(pop_meta["affected_population"])
        if _close(table_sum, meta_sum, atol=1.0):
            checks.append(
                CheckResult("table_vs_metadata_affected_sum", "PASS", f"{table_sum:.3f} ~= {meta_sum:.3f}")
            )
        else:
            rel_diff = abs(table_sum - meta_sum) / max(abs(meta_sum), 1.0)
            if rel_diff <= 0.05:
                warnings += 1
                checks.append(
                    CheckResult("table_vs_metadata_affected_sum", "WARN", f"rel_diff={rel_diff:.4%}")
                )
            else:
                failures += 1
                checks.append(
                    CheckResult("table_vs_metadata_affected_sum", "FAIL", f"rel_diff={rel_diff:.4%}")
                )

    if "pop_weighted_event_count_sum" in df.columns and "pop_weighted_mean_event_count" in pop_meta:
        table_sum = float(df["pop_weighted_event_count_sum"].sum())
        pop_total = float(df["pop_total"].sum()) if "pop_total" in df.columns else 0.0
        table_mean = table_sum / pop_total if pop_total > 0 else 0.0
        meta_mean = float(pop_meta["pop_weighted_mean_event_count"])
        if _close(table_mean, meta_mean, atol=1e-3):
            checks.append(
                CheckResult(
                    "table_vs_metadata_pop_weighted_mean_event_count",
                    "PASS",
                    f"{table_mean:.6f} ~= {meta_mean:.6f}",
                )
            )
        else:
            rel_diff = abs(table_mean - meta_mean) / max(abs(meta_mean), 1e-9)
            if rel_diff <= 0.05:
                warnings += 1
                checks.append(
                    CheckResult(
                        "table_vs_metadata_pop_weighted_mean_event_count",
                        "WARN",
                        f"rel_diff={rel_diff:.4%}",
                    )
                )
            else:
                failures += 1
                checks.append(
                    CheckResult(
                        "table_vs_metadata_pop_weighted_mean_event_count",
                        "FAIL",
                        f"rel_diff={rel_diff:.4%}",
                    )
                )

    viol_cfg = metadata.get("violence_config", {})
    supported = viol_cfg.get("supported_event_types")
    included = viol_cfg.get("included_event_types")
    if isinstance(supported, list) and isinstance(included, list) and included:
        unknown = sorted(set(included) - set(supported))
        if unknown:
            failures += 1
            checks.append(CheckResult("included_event_types_subset_supported", "FAIL", ",".join(unknown)))
        else:
            checks.append(
                CheckResult("included_event_types_subset_supported", "PASS", f"{len(included)} types")
            )
    else:
        warnings += 1
        checks.append(CheckResult("included_event_types_subset_supported", "WARN", "metadata missing"))

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
    lines.append(f"# Violence Parity Report: {Path(report['run_dir']).name}")
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
