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

    recorded_base = (metadata.get("paths") or {}).get("base")
    if recorded_base and Path(recorded_base).resolve() == run_dir.resolve():
        checks.append(CheckResult("run_dir_matches_metadata_base", "PASS", recorded_base))
    else:
        failures += 1
        checks.append(
            CheckResult(
                "run_dir_matches_metadata_base",
                "FAIL",
                f"run_dir={run_dir.resolve()}, metadata.paths.base={recorded_base}",
            )
        )

    preflight = metadata.get("preflight_coverage", {})
    glofas_sample = preflight.get("glofas_sample", {})
    if glofas_sample.get("ok") is True:
        checks.append(CheckResult("preflight_glofas_sample_ok", "PASS", "true"))
    else:
        failures += 1
        checks.append(CheckResult("preflight_glofas_sample_ok", "FAIL", f"value={glofas_sample.get('ok')}"))

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

    table_meta = metadata.get("admin_table_hydrodrought") or {}
    table_path_str = table_meta.get("path", "")
    if not table_path_str:
        # admin_hydrodrought_table is recorded as an artifact, not a top-level
        # key; fall back to the artifacts list.
        for art in metadata.get("artifacts", []):
            if art.get("kind") == "admin_hydrodrought_table":
                table_path_str = art.get("path", "")
                break
    table_path = _is_abs_or_repo_rel(table_path_str)
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
    if pcode_col is None:
        failures += 1
        checks.append(CheckResult("admin_table_pcode_column", "FAIL", "missing adm{level}_pcode column"))
    else:
        checks.append(CheckResult("admin_table_pcode_column", "PASS", pcode_col))
    if "pop_total" not in df.columns:
        failures += 1
        checks.append(CheckResult("admin_table_required_columns", "FAIL", "pop_total"))
    else:
        checks.append(CheckResult("admin_table_required_columns", "PASS", "ok"))

    if "pop_total" in df.columns and (df["pop_total"] < 0).any():
        failures += 1
        checks.append(CheckResult("admin_table_pop_total_non_negative", "FAIL", "negative pop_total"))
    else:
        checks.append(CheckResult("admin_table_pop_total_non_negative", "PASS", "ok"))

    masks = metadata.get("hydrodrought_masks", {})
    products = masks.get("products", {})

    for key, product in products.items():
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
        meta_sum = float(product.get("pop_affected_sum", float("nan")))
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

        ras_path = _is_abs_or_repo_rel(product.get("pop_affected_path", ""))
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

    # An "any-occurrence" mask can never have less affected population than
    # its own persistence variant (persistence is a strict subset).
    for key in list(products.keys()):
        if key.endswith("m") and "_p" in key:
            continue
        persistence_key = next((k for k in products if k.startswith(f"{key}_p") and k.endswith("m")), None)
        if persistence_key is None:
            continue
        c_any = f"pop_affected_{key}"
        c_persist = f"pop_affected_{persistence_key}"
        if c_any in df.columns and c_persist in df.columns:
            if (df[c_any] + 1e-6 >= df[c_persist]).all():
                checks.append(CheckResult(f"monotonic_{key}_ge_{persistence_key}", "PASS", "ok"))
            else:
                failures += 1
                checks.append(
                    CheckResult(
                        f"monotonic_{key}_ge_{persistence_key}",
                        "FAIL",
                        "persistence variant has higher affected population than its any-occurrence base",
                    )
                )

    qc = metadata.get("hydrodrought_qc", {})
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
                CheckResult("default_threshold_key_match", "FAIL", f"metadata={default_key}, qc={qc_default}")
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
    lines.append(f"# Hydrological Drought Parity Report: {Path(report['run_dir']).name}")
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
