from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


PIPELINES = ("spei", "utci", "flood", "violence")


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_report_df(path_or_df: str | Path | pd.DataFrame) -> pd.DataFrame:
    if isinstance(path_or_df, pd.DataFrame):
        return path_or_df.copy()
    p = Path(path_or_df)
    if not p.exists():
        raise FileNotFoundError(f"Missing report: {p.resolve()}")
    return pd.read_csv(p)


def _step_key(task_id: int, pipeline: str) -> str:
    return f"{task_id}:{pipeline}"


def _normalize_pipeline_list(pipelines: list[str] | None) -> list[str]:
    if not pipelines:
        return list(PIPELINES)
    out: list[str] = []
    for p in pipelines:
        norm = str(p).strip().lower()
        if norm not in PIPELINES:
            raise ValueError(f"Unsupported pipeline '{p}'. Expected one of {PIPELINES}.")
        out.append(norm)
    return out


def _build_context(row: pd.Series) -> dict[str, Any]:
    return {
        "task_id": int(row["task_id"]),
        "iso3": str(row["iso3"]).upper(),
        "as_of_date": str(row["as_of_date"]),
        "lookback_months": int(row["lookback_months"]),
        "target_adm_level": int(row["target_adm_level"]),
        "m49_code": str(row.get("m49_code", "")),
        "admin_layer": str(row.get("admin_layer", f"admin{int(row['target_adm_level'])}")),
        "worldpop_path": str(row.get("worldpop_path", "")),
        "acled_path": str(row.get("acled_path", "")),
    }


def _is_pipeline_eligible(row: pd.Series, pipeline: str) -> tuple[bool, str]:
    can_run_col = f"can_run_{pipeline}"
    preflight_col = f"{pipeline}_preflight_status"
    if not bool(row.get("is_valid_manifest", True)):
        return False, "manifest_invalid"
    if not bool(row.get(can_run_col, False)):
        return False, f"{can_run_col}_false"
    status = str(row.get(preflight_col, "SKIP")).upper()
    if status == "FAIL":
        return False, f"{preflight_col}_fail"
    if status == "SKIP":
        return False, f"{preflight_col}_skip"
    return True, "eligible"


def _default_violence_cmd(admin_path: Path, output_root: Path) -> str:
    return (
        "env PYTHONPATH=src python scripts/run_violence_pipeline.py "
        "--iso3 {iso3} "
        "--as-of-date {as_of_date} "
        "--lookback-months {lookback_months} "
        "--target-adm-level {target_adm_level} "
        "--admin-path " + str(admin_path) + " "
        "--admin-layer {admin_layer} "
        "--worldpop-path {worldpop_path} "
        "--acled-csv {acled_path} "
        "--output-root " + str(output_root)
    )


def _default_spei_cmd(admin_path: Path, output_root: Path) -> str:
    return (
        "env PYTHONPATH=src python scripts/run_spei_pipeline.py "
        "--iso3 {iso3} "
        "--as-of-date {as_of_date} "
        "--lookback-months {lookback_months} "
        "--target-adm-level {target_adm_level} "
        "--admin-path " + str(admin_path) + " "
        "--output-root " + str(output_root)
    )


def _default_utci_cmd(admin_path: Path, output_root: Path) -> str:
    return (
        "env PYTHONPATH=src python scripts/run_utci_pipeline.py "
        "--iso3 {iso3} "
        "--as-of-date {as_of_date} "
        "--lookback-months {lookback_months} "
        "--target-adm-level {target_adm_level} "
        "--admin-path " + str(admin_path) + " "
        "--output-root " + str(output_root)
    )


def _default_flood_cmd(admin_path: Path, output_root: Path) -> str:
    return (
        "env PYTHONPATH=src python scripts/run_flood_pipeline.py "
        "--iso3 {iso3} "
        "--as-of-date {as_of_date} "
        "--lookback-months {lookback_months} "
        "--target-adm-level {target_adm_level} "
        "--admin-path " + str(admin_path) + " "
        "--output-root " + str(output_root)
    )


def _write_partial_reports(out_dir: Path, rows: list[dict[str, Any]], total_steps: int) -> None:
    df = pd.DataFrame(rows)
    out_csv = out_dir / "batch_run_report.csv"
    out_json = out_dir / "batch_run_report.json"
    df.to_csv(out_csv, index=False)
    out_json.write_text(
        json.dumps(
            {
                "n_rows": int(len(df)),
                "total_steps": int(total_steps),
                "rows": df.to_dict(orient="records"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_status(
    status_path: Path,
    started_utc: str,
    total_steps: int,
    completed_steps: int,
    running: dict[str, Any] | None,
    note: str,
) -> None:
    _write_json(
        status_path,
        {
            "status": "RUNNING",
            "started_utc": started_utc,
            "completed_steps": int(completed_steps),
            "total_steps": int(total_steps),
            "pct_complete": float((completed_steps / total_steps) * 100.0) if total_steps else 100.0,
            "running": running,
            "last_updated_utc": _now_utc(),
            "note": note,
        },
    )


def run_batch_execution(
    readiness: str | Path | pd.DataFrame,
    preflight: str | Path | pd.DataFrame,
    out_dir: Path = Path("./outputs/batch/run"),
    pipelines: list[str] | None = None,
    command_templates: dict[str, str | None] | None = None,
    admin_path: Path = Path("./data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip"),
    output_root: Path = Path("./outputs"),
    max_retries: int = 1,
    stop_on_failure: bool = False,
    resume: bool = True,
    dry_run: bool = False,
    heartbeat_seconds: int = 30,
    step_timeout_minutes: int = 0,
    run_cwd: Path | None = None,
) -> dict[str, Any]:
    ready_df = _load_report_df(readiness)
    pf_df = _load_report_df(preflight)
    if ready_df.empty:
        return {"summary": {"n_steps": 0, "n_success": 0, "n_failed": 0, "n_skipped": 0}, "rows": []}

    required_ready = {"task_id", "iso3", "as_of_date", "lookback_months", "target_adm_level"}
    missing = sorted(required_ready - set(ready_df.columns))
    if missing:
        raise ValueError(f"Readiness report missing required columns: {missing}")
    if "task_id" not in pf_df.columns:
        raise ValueError("Preflight report missing required column: task_id")

    merged = ready_df.merge(
        pf_df[["task_id"] + [c for c in pf_df.columns if c.endswith("_preflight_status")]],
        on="task_id",
        how="left",
        suffixes=("", "_pf"),
    )

    pipeline_order = _normalize_pipeline_list(pipelines)
    out_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = out_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    status_path = out_dir / "batch_run_status.json"

    templates: dict[str, str | None] = {
        "spei": _default_spei_cmd(admin_path=admin_path, output_root=output_root),
        "utci": _default_utci_cmd(admin_path=admin_path, output_root=output_root),
        "flood": _default_flood_cmd(admin_path=admin_path, output_root=output_root),
        "violence": _default_violence_cmd(admin_path=admin_path, output_root=output_root),
    }
    if command_templates:
        templates.update(command_templates)

    total_steps = int(len(merged) * len(pipeline_order))
    started_utc = _now_utc()
    _write_status(
        status_path=status_path,
        started_utc=started_utc,
        total_steps=total_steps,
        completed_steps=0,
        running=None,
        note="Batch run started.",
    )

    existing_rows: list[dict[str, Any]] = []
    existing_done: set[str] = set()
    report_path = out_dir / "batch_run_report.csv"
    if resume and report_path.exists():
        prior = pd.read_csv(report_path)
        if not prior.empty:
            latest_rows_by_step: dict[str, dict[str, Any]] = {}
            for _, r in prior.iterrows():
                step = _step_key(int(r["task_id"]), str(r["pipeline"]))
                latest_rows_by_step[step] = r.to_dict()
            existing_rows = list(latest_rows_by_step.values())
            for r in existing_rows:
                step = _step_key(int(r["task_id"]), str(r["pipeline"]))
                if str(r.get("status", "")).upper() in {"SUCCESS", "SKIP", "DRY_RUN"}:
                    existing_done.add(step)

    rows: list[dict[str, Any]] = list(existing_rows)
    completed = len(existing_done)
    if resume and existing_rows:
        _write_partial_reports(out_dir, rows, total_steps)

    for _, row in merged.sort_values(["task_id"]).iterrows():
        ctx = _build_context(row)
        for pipeline in pipeline_order:
            step = _step_key(ctx["task_id"], pipeline)
            if resume and step in existing_done:
                continue

            eligible, reason = _is_pipeline_eligible(row, pipeline)
            cmd_template = templates.get(pipeline)
            rec: dict[str, Any] = {
                "task_id": ctx["task_id"],
                "iso3": ctx["iso3"],
                "as_of_date": ctx["as_of_date"],
                "lookback_months": ctx["lookback_months"],
                "target_adm_level": ctx["target_adm_level"],
                "pipeline": pipeline,
                "started_utc": _now_utc(),
                "ended_utc": None,
                "duration_seconds": None,
                "attempts": 0,
                "status": "",
                "exit_code": None,
                "log_path": "",
                "error": "",
                "command": "",
            }
            if not eligible:
                rec["status"] = "SKIP"
                rec["error"] = reason
                rec["ended_utc"] = _now_utc()
                rows.append(rec)
                completed += 1
                _write_partial_reports(out_dir, rows, total_steps)
                _write_status(
                    status_path=status_path,
                    started_utc=started_utc,
                    total_steps=total_steps,
                    completed_steps=completed,
                    running=None,
                    note=f"Skipped {pipeline} for task {ctx['task_id']} ({reason}).",
                )
                continue

            if not cmd_template:
                rec["status"] = "SKIP"
                rec["error"] = "missing_command_template"
                rec["ended_utc"] = _now_utc()
                rows.append(rec)
                completed += 1
                _write_partial_reports(out_dir, rows, total_steps)
                _write_status(
                    status_path=status_path,
                    started_utc=started_utc,
                    total_steps=total_steps,
                    completed_steps=completed,
                    running=None,
                    note=f"Skipped {pipeline} for task {ctx['task_id']} (no command template).",
                )
                continue

            cmd = cmd_template.format(**ctx)
            rec["command"] = cmd
            if dry_run:
                rec["status"] = "DRY_RUN"
                rec["ended_utc"] = _now_utc()
                rows.append(rec)
                completed += 1
                _write_partial_reports(out_dir, rows, total_steps)
                _write_status(
                    status_path=status_path,
                    started_utc=started_utc,
                    total_steps=total_steps,
                    completed_steps=completed,
                    running=None,
                    note=f"Planned {pipeline} for task {ctx['task_id']} (dry-run).",
                )
                continue

            attempts_allowed = max(1, int(max_retries))
            run_ok = False
            run_start = time.time()
            for attempt in range(1, attempts_allowed + 1):
                rec["attempts"] = attempt
                log_path = logs_dir / (
                    f"task_{ctx['task_id']:04d}_{ctx['iso3']}_{pipeline}_attempt{attempt}.log"
                )
                rec["log_path"] = str(log_path)

                _write_status(
                    status_path=status_path,
                    started_utc=started_utc,
                    total_steps=total_steps,
                    completed_steps=completed,
                    running={
                        "task_id": ctx["task_id"],
                        "iso3": ctx["iso3"],
                        "pipeline": pipeline,
                        "attempt": attempt,
                        "max_attempts": attempts_allowed,
                        "command": cmd,
                        "log_path": str(log_path),
                    },
                    note=f"Running {pipeline} for {ctx['iso3']} (attempt {attempt}/{attempts_allowed}).",
                )

                with log_path.open("w", encoding="utf-8") as log_f:
                    log_f.write(f"$ {cmd}\n\n")
                    log_f.flush()
                    proc = subprocess.Popen(
                        cmd,
                        shell=True,
                        stdout=log_f,
                        stderr=subprocess.STDOUT,
                        cwd=str(run_cwd or Path.cwd()),
                    )
                    step_start = time.time()
                    timeout_s = int(step_timeout_minutes * 60) if int(step_timeout_minutes) > 0 else 0
                    while True:
                        rc = proc.poll()
                        now = time.time()
                        if rc is not None:
                            rec["exit_code"] = int(rc)
                            break
                        if timeout_s > 0 and (now - step_start) > timeout_s:
                            proc.terminate()
                            try:
                                proc.wait(timeout=15)
                            except Exception:
                                proc.kill()
                            rec["exit_code"] = 124
                            rec["error"] = f"timeout>{step_timeout_minutes}m"
                            break
                        _write_status(
                            status_path=status_path,
                            started_utc=started_utc,
                            total_steps=total_steps,
                            completed_steps=completed,
                            running={
                                "task_id": ctx["task_id"],
                                "iso3": ctx["iso3"],
                                "pipeline": pipeline,
                                "attempt": attempt,
                                "max_attempts": attempts_allowed,
                                "elapsed_seconds": round(now - step_start, 1),
                                "log_path": str(log_path),
                            },
                            note=f"Heartbeat: {pipeline} for {ctx['iso3']} still running.",
                        )
                        time.sleep(max(5, int(heartbeat_seconds)))

                exit_code = rec.get("exit_code")
                if isinstance(exit_code, int) and exit_code == 0:
                    run_ok = True
                    break

            rec["ended_utc"] = _now_utc()
            rec["duration_seconds"] = round(float(time.time() - run_start), 2)
            if run_ok:
                rec["status"] = "SUCCESS"
            else:
                rec["status"] = "FAILED"
                if not rec["error"]:
                    rec["error"] = "nonzero_exit"

            rows.append(rec)
            completed += 1
            _write_partial_reports(out_dir, rows, total_steps)
            _write_status(
                status_path=status_path,
                started_utc=started_utc,
                total_steps=total_steps,
                completed_steps=completed,
                running=None,
                note=f"Completed {pipeline} for {ctx['iso3']} with status {rec['status']}.",
            )

            if rec["status"] == "FAILED" and stop_on_failure:
                summary = _summarize_rows(rows)
                _write_json(
                    status_path,
                    {
                        "status": "FAILED",
                        "started_utc": started_utc,
                        "completed_steps": int(completed),
                        "total_steps": int(total_steps),
                        "pct_complete": float((completed / total_steps) * 100.0) if total_steps else 100.0,
                        "last_updated_utc": _now_utc(),
                        "note": f"Stopped early on failure: task {ctx['task_id']} {pipeline}",
                        "summary": summary,
                    },
                )
                return {
                    "summary": summary,
                    "report_csv": str(out_dir / "batch_run_report.csv"),
                    "report_json": str(out_dir / "batch_run_report.json"),
                    "status_json": str(status_path),
                    "rows": pd.DataFrame(rows),
                }

    summary = _summarize_rows(rows)
    final_status = "COMPLETED" if int(summary["n_failed"]) == 0 else "COMPLETED_WITH_ERRORS"
    _write_json(
        status_path,
        {
            "status": final_status,
            "started_utc": started_utc,
            "completed_steps": int(completed),
            "total_steps": int(total_steps),
            "pct_complete": float((completed / total_steps) * 100.0) if total_steps else 100.0,
            "last_updated_utc": _now_utc(),
            "note": "Batch run finished.",
            "summary": summary,
        },
    )
    return {
        "summary": summary,
        "report_csv": str(out_dir / "batch_run_report.csv"),
        "report_json": str(out_dir / "batch_run_report.json"),
        "status_json": str(status_path),
        "rows": pd.DataFrame(rows),
    }


def _summarize_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
    df = pd.DataFrame(rows)
    if df.empty:
        return {"n_steps": 0, "n_success": 0, "n_failed": 0, "n_skipped": 0, "n_dry_run": 0}
    status = df["status"].astype(str).str.upper()
    return {
        "n_steps": int(len(df)),
        "n_success": int((status == "SUCCESS").sum()),
        "n_failed": int((status == "FAILED").sum()),
        "n_skipped": int((status == "SKIP").sum()),
        "n_dry_run": int((status == "DRY_RUN").sum()),
    }
