from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import rasterio


@dataclass
class CheckResult:
    name: str
    status: str
    detail: str


def _is_abs_or_repo_rel(path_str: str) -> Path:
    p = Path(path_str)
    return p if p.is_absolute() else Path.cwd() / p


def _sum_raster(path: Path) -> float:
    with rasterio.open(path) as src:
        arr = src.read(1, masked=True)
        return float(arr.sum())


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
        checks.append(
            CheckResult(
                "run_id_matches_dir",
                "FAIL",
                f"run_dir={run_dir.name}, run_id={run_id}",
            )
        )

    preflight = metadata.get("preflight_coverage", {})
    spei_cov = preflight.get("spei_sample", {})
    if spei_cov.get("full_coverage") is True:
        checks.append(CheckResult("preflight_spei_full_coverage", "PASS", "true"))
    else:
        failures += 1
        checks.append(
            CheckResult(
                "preflight_spei_full_coverage",
                "FAIL",
                f"value={spei_cov.get('full_coverage')}",
            )
        )

    wp_cov = preflight.get("worldpop", {})
    wp_full = wp_cov.get("full_coverage")
    if wp_full is True:
        checks.append(CheckResult("preflight_worldpop_full_coverage", "PASS", "true"))
    else:
        warnings += 1
        checks.append(
            CheckResult(
                "preflight_worldpop_full_coverage",
                "WARN",
                f"value={wp_full}, pct={wp_cov.get('coverage_pct')}",
            )
        )

    table_meta = metadata.get("admin_table_spei") or metadata.get("admin2_table_spei", {})
    table_path = _is_abs_or_repo_rel(table_meta.get("path", ""))
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
    required_cols = {"pop_total"}
    if pcode_col is None:
        failures += 1
        checks.append(CheckResult("admin_table_pcode_column", "FAIL", "missing adm{level}_pcode column"))
    else:
        checks.append(CheckResult("admin_table_pcode_column", "PASS", pcode_col))
    missing = sorted(required_cols - set(df.columns))
    if missing:
        failures += 1
        checks.append(CheckResult("admin_table_required_columns", "FAIL", ",".join(missing)))
    else:
        checks.append(CheckResult("admin_table_required_columns", "PASS", "ok"))

    if (df["pop_total"] < 0).any():
        failures += 1
        checks.append(CheckResult("admin_table_pop_total_non_negative", "FAIL", "negative pop_total"))
    else:
        checks.append(CheckResult("admin_table_pop_total_non_negative", "PASS", "ok"))

    masks = metadata.get("spei_masks", {})
    products = masks.get("products", {})
    keys = list(products.keys())
    keys_sorted = sorted(keys, key=lambda k: products[k].get("threshold", 0.0), reverse=True)

    for key in keys:
        pop_col = f"pop_affected_{key}"
        pct_col = f"pct_affected_{key}"
        if pop_col not in df.columns:
            failures += 1
            checks.append(CheckResult(f"{key}_table_pop_col", "FAIL", pop_col))
            continue
        if pct_col not in df.columns:
            failures += 1
            checks.append(CheckResult(f"{key}_table_pct_col", "FAIL", pct_col))
            continue
        checks.append(CheckResult(f"{key}_table_cols", "PASS", "ok"))

        if (df[pop_col] < -1e-6).any():
            failures += 1
            checks.append(CheckResult(f"{key}_table_non_negative", "FAIL", "negative values"))
        else:
            checks.append(CheckResult(f"{key}_table_non_negative", "PASS", "ok"))

        pct_ok = ((df[pct_col] >= -1e-6) & (df[pct_col] <= 100.0001)).all()
        if pct_ok:
            checks.append(CheckResult(f"{key}_pct_bounds", "PASS", "0..100"))
        else:
            failures += 1
            checks.append(CheckResult(f"{key}_pct_bounds", "FAIL", "outside 0..100"))

        table_sum = float(df[pop_col].sum())
        meta_sum = float(products[key].get("pop_affected_sum", float("nan")))
        if _close(table_sum, meta_sum, atol=1e-2):
            checks.append(
                CheckResult(f"{key}_table_vs_metadata_sum", "PASS", f"{table_sum:.3f} ~= {meta_sum:.3f}")
            )
        else:
            rel_diff = abs(table_sum - meta_sum) / max(abs(meta_sum), 1.0)
            if rel_diff <= 0.005:
                warnings += 1
                checks.append(
                    CheckResult(
                        f"{key}_table_vs_metadata_sum",
                        "WARN",
                        f"{table_sum:.3f} != {meta_sum:.3f} (rel_diff={rel_diff:.4%})",
                    )
                )
            else:
                failures += 1
                checks.append(
                    CheckResult(
                        f"{key}_table_vs_metadata_sum",
                        "FAIL",
                        f"{table_sum:.3f} != {meta_sum:.3f} (rel_diff={rel_diff:.4%})",
                    )
                )

        ras_path = _is_abs_or_repo_rel(products[key].get("pop_affected_path", ""))
        if ras_path.exists():
            ras_sum = _sum_raster(ras_path)
            if _close(ras_sum, meta_sum, atol=1.0):
                checks.append(
                    CheckResult(f"{key}_raster_vs_metadata_sum", "PASS", f"{ras_sum:.3f} ~= {meta_sum:.3f}")
                )
            else:
                failures += 1
                checks.append(
                    CheckResult(f"{key}_raster_vs_metadata_sum", "FAIL", f"{ras_sum:.3f} != {meta_sum:.3f}")
                )
        else:
            failures += 1
            checks.append(CheckResult(f"{key}_raster_exists", "FAIL", str(ras_path)))

    for i in range(len(keys_sorted) - 1):
        k_loose = keys_sorted[i]
        k_strict = keys_sorted[i + 1]
        c_loose = f"pop_affected_{k_loose}"
        c_strict = f"pop_affected_{k_strict}"
        if c_loose in df.columns and c_strict in df.columns:
            if (df[c_loose] + 1e-6 >= df[c_strict]).all():
                checks.append(
                    CheckResult(
                        f"monotonic_{k_loose}_ge_{k_strict}",
                        "PASS",
                        "ok",
                    )
                )
            else:
                failures += 1
                checks.append(
                    CheckResult(
                        f"monotonic_{k_loose}_ge_{k_strict}",
                        "FAIL",
                        "found admin rows where stricter threshold has higher affected pop",
                    )
                )

    qc = metadata.get("spei_qc_figures", {})
    qc_csv = _is_abs_or_repo_rel(qc.get("qc_csv", ""))
    if qc_csv.exists():
        qcdf = pd.read_csv(qc_csv)
        if len(qcdf) == 1:
            checks.append(CheckResult("qc_csv_rowcount", "PASS", "1"))
        else:
            warnings += 1
            checks.append(CheckResult("qc_csv_rowcount", "WARN", f"rows={len(qcdf)}"))
        default_key = masks.get("default_key")
        qc_default = str(qcdf.loc[0, "default_threshold_key"]) if len(qcdf) else ""
        if default_key == qc_default:
            checks.append(CheckResult("default_threshold_key_match", "PASS", default_key or ""))
        else:
            failures += 1
            checks.append(
                CheckResult(
                    "default_threshold_key_match",
                    "FAIL",
                    f"metadata={default_key}, qc={qc_default}",
                )
            )
    else:
        warnings += 1
        checks.append(CheckResult("qc_csv_exists", "WARN", str(qc_csv)))

    missing_artifacts: list[str] = []
    for art in metadata.get("artifacts", []):
        p = _is_abs_or_repo_rel(art.get("path", ""))
        if not p.exists():
            missing_artifacts.append(str(p))
    if missing_artifacts:
        warnings += 1
        checks.append(
            CheckResult(
                "metadata_artifacts_exist",
                "WARN",
                f"missing={len(missing_artifacts)}",
            )
        )
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
    lines.append(f"# SPEI Parity Report: {Path(report['run_dir']).name}")
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
