from __future__ import annotations

import json
from pathlib import Path

from ..notebook_runner import execute_notebook, parameterize_notebook


def run_notebook_hazard_pipeline(
    *,
    pipeline_name: str,
    notebook_path: Path,
    iso3: str,
    as_of_date: str,
    lookback_months: int,
    output_root: Path,
    admin_path: Path,
    target_adm_level: int,
    dry_run: bool,
    timeout_seconds: int,
    run_cwd: Path | None = None,
    extra_replacements: dict[str, str] | None = None,
) -> tuple[int, dict]:
    logs_dir = output_root / "_batch_notebook_runs" / pipeline_name / iso3.upper()
    logs_dir.mkdir(parents=True, exist_ok=True)
    replacements = {
        "ISO3": f'"{iso3.upper()}"',
        "AS_OF_DATE": f'"{as_of_date}"',
        "LOOKBACK_MONTHS": str(int(lookback_months)),
        "RECENT_MONTHS": str(int(lookback_months)),
        "OUT_ROOT": f'Path(r"{str(output_root)}")',
        "COD_GDB_ZIP": f'Path(r"{str(admin_path)}")',
        "GDB_ZIP_PATH": f'Path(r"{str(admin_path)}")',
        "ADMIN2_LAYER": f'"admin{int(target_adm_level)}"',
        "COD_ADMIN2_LAYER": f'"admin{int(target_adm_level)}"',
        "PRECHECK_MAKE_PLOTS": "False",
    }
    if extra_replacements:
        replacements.update(extra_replacements)

    patched_nb, counts = parameterize_notebook(
        source_nb=notebook_path,
        out_dir=logs_dir,
        replacements=replacements,
        output_stem=f"{pipeline_name}_{iso3.lower()}_{as_of_date}",
    )

    payload = {
        "pipeline": pipeline_name,
        "iso3": iso3.upper(),
        "as_of_date": as_of_date,
        "lookback_months": int(lookback_months),
        "target_adm_level": int(target_adm_level),
        "output_root": str(output_root),
        "admin_path": str(admin_path),
        "notebook_source": str(notebook_path),
        "notebook_parameterized": str(patched_nb),
        "assignment_replacements": counts,
    }
    if dry_run:
        payload["status"] = "DRY_RUN"
        return 0, payload

    result = execute_notebook(
        notebook_path=patched_nb,
        executed_out_dir=logs_dir,
        timeout_seconds=int(timeout_seconds),
        run_cwd=run_cwd,
    )
    payload.update(result)
    payload["status"] = "SUCCESS" if int(result["exit_code"]) == 0 else "FAILED"
    rc = 0 if int(result["exit_code"]) == 0 else 2
    return rc, payload


def print_payload(payload: dict) -> None:
    print(json.dumps(payload, indent=2))
