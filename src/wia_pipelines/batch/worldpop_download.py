from __future__ import annotations

import csv
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class WorldPopDownloadSpec:
    iso3: str
    url: str
    output_path: Path


def build_worldpop_filename(
    iso3: str,
    year: int = 2025,
    release: str = "R2025A",
    version: str = "v1",
    resolution: str = "100m",
    constrained_tag: str = "CN",
) -> str:
    return f"{iso3.lower()}_pop_{year}_{constrained_tag}_{resolution}_{release}_{version}.tif"


def build_worldpop_url(
    iso3: str,
    year: int = 2025,
    release: str = "R2025A",
    version: str = "v1",
    resolution: str = "100m",
    constrained_folder: str = "constrained",
    base_url: str = "https://data.worldpop.org/GIS/Population/Global_2015_2030",
) -> str:
    filename = build_worldpop_filename(
        iso3=iso3,
        year=year,
        release=release,
        version=version,
        resolution=resolution,
    )
    return (
        f"{base_url.rstrip('/')}/{release}/{year}/{iso3.upper()}/{version}/"
        f"{resolution}/{constrained_folder}/{filename}"
    )


def build_worldpop_download_plan(
    tasks: pd.DataFrame,
    worldpop_dir: Path,
    year: int = 2025,
    release: str = "R2025A",
    version: str = "v1",
    resolution: str = "100m",
    constrained_folder: str = "constrained",
    base_url: str = "https://data.worldpop.org/GIS/Population/Global_2015_2030",
) -> list[WorldPopDownloadSpec]:
    if "iso3" not in tasks.columns:
        raise ValueError("tasks dataframe must include an 'iso3' column")

    valid = tasks.copy()
    if "is_valid_manifest" in valid.columns:
        valid = valid[valid["is_valid_manifest"].fillna(False)]

    isos = sorted(set(valid["iso3"].astype(str).str.upper().tolist()))
    specs: list[WorldPopDownloadSpec] = []
    for iso3 in isos:
        filename = build_worldpop_filename(
            iso3=iso3,
            year=year,
            release=release,
            version=version,
            resolution=resolution,
        )
        out_path = worldpop_dir / filename
        specs.append(
            WorldPopDownloadSpec(
                iso3=iso3,
                url=build_worldpop_url(
                    iso3=iso3,
                    year=year,
                    release=release,
                    version=version,
                    resolution=resolution,
                    constrained_folder=constrained_folder,
                    base_url=base_url,
                ),
                output_path=out_path,
            )
        )
    return specs


def _download_file(url: str, output_path: Path, timeout_seconds: int = 120) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_seconds) as r:
        if getattr(r, "status", 200) != 200:
            raise RuntimeError(f"HTTP status {getattr(r, 'status', 'unknown')} for {url}")
        with output_path.open("wb") as f:
            while True:
                chunk = r.read(1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)


def download_worldpop_specs(
    specs: list[WorldPopDownloadSpec],
    force: bool = False,
    timeout_seconds: int = 120,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for spec in specs:
        out = spec.output_path
        status = ""
        error = ""
        size_bytes: int | None = None

        if out.exists() and out.stat().st_size > 0 and not force:
            status = "EXISTS"
            size_bytes = int(out.stat().st_size)
        else:
            if out.exists() and force:
                out.unlink()
            try:
                _download_file(spec.url, out, timeout_seconds=timeout_seconds)
                size_bytes = int(out.stat().st_size) if out.exists() else 0
                if size_bytes <= 0:
                    raise RuntimeError("downloaded file is empty")
                status = "DOWNLOADED"
            except (
                urllib.error.HTTPError,
                urllib.error.URLError,
                TimeoutError,
                RuntimeError,
                OSError,
            ) as exc:
                status = "FAILED"
                error = str(exc)
                if out.exists() and out.stat().st_size == 0:
                    out.unlink()

        rows.append(
            {
                "iso3": spec.iso3,
                "status": status,
                "url": spec.url,
                "output_path": str(spec.output_path),
                "size_bytes": size_bytes,
                "error": error,
            }
        )

    return pd.DataFrame(rows)


def write_download_report(report: pd.DataFrame, out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / "worldpop_download_report.csv"
    out_json = out_dir / "worldpop_download_report.json"
    summary_json = out_dir / "worldpop_download_summary.json"

    report.to_csv(out_csv, index=False, quoting=csv.QUOTE_MINIMAL)
    out_json.write_text(
        json.dumps(report.to_dict(orient="records"), indent=2),
        encoding="utf-8",
    )

    payload = {
        "n_total": int(len(report)),
        "n_downloaded": int((report["status"] == "DOWNLOADED").sum()) if not report.empty else 0,
        "n_exists": int((report["status"] == "EXISTS").sum()) if not report.empty else 0,
        "n_failed": int((report["status"] == "FAILED").sum()) if not report.empty else 0,
        "report_csv": str(out_csv),
        "report_json": str(out_json),
    }
    summary_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return {
        "report_csv": str(out_csv),
        "report_json": str(out_json),
        "summary_json": str(summary_json),
    }
