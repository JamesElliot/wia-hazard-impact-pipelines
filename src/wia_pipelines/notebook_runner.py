from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _replace_assignment_lines(source: str, replacements: dict[str, str]) -> tuple[str, dict[str, int]]:
    counts = {k: 0 for k in replacements}
    lines = source.splitlines(keepends=True)
    out: list[str] = []
    for line in lines:
        replaced = False
        for key, expr in replacements.items():
            pattern = rf"^(\s*{re.escape(key)}\s*=\s*).*$"
            if re.match(pattern, line):
                prefix = re.sub(pattern, r"\1", line).rstrip("\n")
                out.append(f"{prefix}{expr}\n")
                counts[key] += 1
                replaced = True
                break
        if not replaced:
            out.append(line)
    return "".join(out), counts


def parameterize_notebook(
    source_nb: Path,
    out_dir: Path,
    replacements: dict[str, str],
    output_stem: str | None = None,
) -> tuple[Path, dict[str, int]]:
    if not source_nb.exists():
        raise FileNotFoundError(f"Notebook not found: {source_nb.resolve()}")
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = json.loads(source_nb.read_text(encoding="utf-8"))
    total = {k: 0 for k in replacements}
    for cell in payload.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source", []))
        patched, counts = _replace_assignment_lines(src, replacements)
        for key, n in counts.items():
            total[key] += n
        cell["source"] = patched

    stem = output_stem or f"{source_nb.stem}.param.{_now_stamp()}"
    patched_nb = out_dir / f"{stem}.ipynb"
    patched_nb.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return patched_nb, total


def execute_notebook(
    notebook_path: Path,
    executed_out_dir: Path,
    timeout_seconds: int = 0,
    run_cwd: Path | None = None,
) -> dict[str, Any]:
    executed_out_dir.mkdir(parents=True, exist_ok=True)
    timeout = "-1" if timeout_seconds <= 0 else str(int(timeout_seconds))
    cmd = [
        "jupyter",
        "nbconvert",
        "--to",
        "notebook",
        "--execute",
        f"--ExecutePreprocessor.timeout={timeout}",
        "--output",
        notebook_path.name,
        "--output-dir",
        str(executed_out_dir),
        str(notebook_path),
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(run_cwd or Path.cwd()),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    output_path = executed_out_dir / notebook_path.name
    return {
        "command": " ".join(cmd),
        "exit_code": int(proc.returncode),
        "stdout": proc.stdout,
        "executed_notebook": str(output_path),
    }
