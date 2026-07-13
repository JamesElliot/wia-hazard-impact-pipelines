from __future__ import annotations

from pathlib import Path
from typing import Any

import json
import pandas as pd


def _add_issue(
    rows: list[dict[str, Any]],
    task: pd.Series,
    pipeline: str,
    severity: str,
    code: str,
    detail: str,
    action: str,
) -> None:
    rows.append(
        {
            "task_id": int(task.get("task_id", -1)),
            "iso3": str(task.get("iso3", "")),
            "as_of_date": str(task.get("as_of_date", "")),
            "lookback_months": int(task.get("lookback_months", 0))
            if pd.notna(task.get("lookback_months"))
            else None,
            "target_adm_level": int(task.get("target_adm_level", 2))
            if pd.notna(task.get("target_adm_level"))
            else None,
            "pipeline": pipeline,
            "severity": severity,
            "code": code,
            "detail": detail,
            "suggested_action": action,
        }
    )


def build_issue_report(readiness: pd.DataFrame, preflight: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    preflight_by_task = {int(r["task_id"]): r for _, r in preflight.iterrows()} if not preflight.empty else {}

    for _, task in readiness.iterrows():
        task_id = int(task["task_id"])
        pf = preflight_by_task.get(task_id)

        if not bool(task.get("is_valid_manifest", False)):
            _add_issue(
                rows,
                task,
                pipeline="all",
                severity="ERROR",
                code="manifest_invalid",
                detail=str(task.get("manifest_errors") or "invalid manifest row"),
                action="Fix ISO3/as_of_date/lookback/admin_level in batch manifest and rerun preflight.",
            )

        if not bool(task.get("worldpop_exists", False)):
            _add_issue(
                rows,
                task,
                pipeline="all",
                severity="ERROR",
                code="missing_worldpop",
                detail=str(task.get("worldpop_path", "")),
                action="Download/add required WorldPop raster file for this ISO3.",
            )

        if not bool(task.get("admin_layer_exists", False)):
            _add_issue(
                rows,
                task,
                pipeline="all",
                severity="ERROR",
                code="missing_admin_layer",
                detail=str(task.get("admin_layer", "")),
                action="Provide COD admin boundary layer for selected admin level.",
            )
        elif not bool(task.get("admin_has_required_cols", False)):
            _add_issue(
                rows,
                task,
                pipeline="all",
                severity="ERROR",
                code="invalid_admin_layer_schema",
                detail="Missing required columns (iso3, geometry or admin code fields).",
                action="Fix/replace COD admin dataset and rerun.",
            )
        elif int(task.get("admin_feature_count", 0)) <= 0:
            _add_issue(
                rows,
                task,
                pipeline="all",
                severity="ERROR",
                code="iso3_not_in_admin",
                detail=f"No features found for {task.get('iso3')} at {task.get('admin_layer')}",
                action="Validate ISO3 code and COD admin data for this country/admin level.",
            )

        if not bool(task.get("acled_exists", False)):
            _add_issue(
                rows,
                task,
                pipeline="violence",
                severity="ERROR",
                code="missing_acled_csv",
                detail=str(task.get("acled_path", "")),
                action="Add ACLED country file or skip violence pipeline for this task.",
            )

        if pf is None:
            _add_issue(
                rows,
                task,
                pipeline="all",
                severity="ERROR",
                code="missing_preflight_row",
                detail="No preflight output generated for task.",
                action="Inspect batch-preflight runtime errors and rerun.",
            )
            continue

        for pipeline in ["spei", "utci", "flood", "violence"]:
            status = str(pf.get(f"{pipeline}_preflight_status", "SKIP")).upper()
            if status == "FAIL":
                _add_issue(
                    rows,
                    task,
                    pipeline=pipeline,
                    severity="ERROR",
                    code=f"{pipeline}_preflight_fail",
                    detail=str(pf.get("preflight_issues", "preflight failure")),
                    action=f"Investigate {pipeline.upper()} preflight errors and data availability.",
                )
            elif status == "WARN":
                _add_issue(
                    rows,
                    task,
                    pipeline=pipeline,
                    severity="WARN",
                    code=f"{pipeline}_preflight_warn",
                    detail=str(pf.get("preflight_issues", "coverage warning")),
                    action=f"Review {pipeline.upper()} coverage warning and decide if acceptable.",
                )

        preflight_issues = str(pf.get("preflight_issues", "")).strip()
        if preflight_issues:
            for token in [t.strip() for t in preflight_issues.split(";") if t.strip()]:
                if ":" in token:
                    code, detail = token.split(":", 1)
                else:
                    code, detail = token, token
                _add_issue(
                    rows,
                    task,
                    pipeline="all",
                    severity="ERROR",
                    code=f"preflight_issue_{code}",
                    detail=detail,
                    action="Inspect detailed preflight logs for this task.",
                )

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(
            columns=[
                "task_id",
                "iso3",
                "as_of_date",
                "lookback_months",
                "target_adm_level",
                "pipeline",
                "severity",
                "code",
                "detail",
                "suggested_action",
            ]
        )

    df = df.drop_duplicates(
        subset=[
            "task_id",
            "pipeline",
            "severity",
            "code",
            "detail",
        ]
    ).sort_values(["severity", "task_id", "pipeline", "code"], ascending=[True, True, True, True])
    return df


def issue_report_markdown(issues: pd.DataFrame, readiness: pd.DataFrame, preflight: pd.DataFrame) -> str:
    n_tasks = int(len(readiness))
    n_err = int((issues["severity"] == "ERROR").sum()) if not issues.empty else 0
    n_warn = int((issues["severity"] == "WARN").sum()) if not issues.empty else 0
    n_ready_all = (
        int(readiness.get("readiness_ok_all", pd.Series(dtype=bool)).fillna(False).sum())
        if not readiness.empty
        else 0
    )

    lines: list[str] = []
    lines.append("# Batch Data/Preflight Issues")
    lines.append("")
    lines.append(f"- Tasks: {n_tasks}")
    lines.append(f"- Readiness OK for all 4 pipelines: {n_ready_all}")
    lines.append(f"- ERROR issues: {n_err}")
    lines.append(f"- WARN issues: {n_warn}")
    lines.append("")

    if issues.empty:
        lines.append("No issues found.")
        lines.append("")
        return "\n".join(lines)

    lines.append("## Issue Table")
    lines.append("")
    lines.append("| Task | ISO3 | Admin | Pipeline | Severity | Code | Detail | Suggested action |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for _, r in issues.iterrows():
        detail = str(r["detail"]).replace("|", "\\|")
        action = str(r["suggested_action"]).replace("|", "\\|")
        lines.append(
            f"| {int(r['task_id'])} | {r['iso3']} | {int(r['target_adm_level'])} | {r['pipeline']} | {r['severity']} | `{r['code']}` | {detail} | {action} |"
        )
    lines.append("")

    return "\n".join(lines)


def write_issue_report(
    readiness: pd.DataFrame,
    preflight: pd.DataFrame,
    out_dir: Path,
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    issues = build_issue_report(readiness=readiness, preflight=preflight)

    out_csv = out_dir / "batch_issues.csv"
    out_md = out_dir / "batch_issues.md"
    out_json = out_dir / "batch_issues_summary.json"

    issues.to_csv(out_csv, index=False)
    out_md.write_text(issue_report_markdown(issues, readiness, preflight), encoding="utf-8")

    payload = {
        "n_tasks": int(len(readiness)),
        "n_issues": int(len(issues)),
        "n_errors": int((issues["severity"] == "ERROR").sum()) if not issues.empty else 0,
        "n_warnings": int((issues["severity"] == "WARN").sum()) if not issues.empty else 0,
        "issues_csv": str(out_csv),
        "issues_md": str(out_md),
    }
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return {
        "issues_csv": str(out_csv),
        "issues_md": str(out_md),
        "issues_summary_json": str(out_json),
    }
