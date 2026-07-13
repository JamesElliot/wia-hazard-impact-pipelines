from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from ..core.worldpop import bbox_coverage_report
from ..hazards.coverage_checks import (
    check_worldpop_coverage,
    prepare_country_admin_context,
    run_cds_single_month_check,
    run_flood_stac_extent_check,
    spei_sample_request,
    utci_sample_request,
)


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_partial_reports(out_dir: Path, report_rows: list[dict[str, Any]], total_tasks: int) -> None:
    df = pd.DataFrame(report_rows)
    out_csv = out_dir / "batch_preflight_report.csv"
    out_json = out_dir / "batch_preflight_report.json"
    df.to_csv(out_csv, index=False)
    out_json.write_text(
        json.dumps(
            {
                "n_tasks": int(total_tasks),
                "n_reports": int(len(df)),
                "reports": df.to_dict(orient="records"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _update_task_status(
    status_path: Path,
    run_started_utc: str,
    total_tasks: int,
    completed_tasks: int,
    task_id: int,
    iso3: str,
    as_of_date: str,
    target_adm_level: int,
    note: str,
) -> None:
    _write_status(
        status_path,
        {
            "status": "RUNNING",
            "started_utc": run_started_utc,
            "completed_tasks": completed_tasks,
            "total_tasks": total_tasks,
            "pct_complete": float((completed_tasks / total_tasks) * 100.0) if total_tasks else 100.0,
            "current_task": {
                "task_id": task_id,
                "iso3": iso3,
                "as_of_date": as_of_date,
                "target_adm_level": target_adm_level,
            },
            "last_updated_utc": _now_utc(),
            "note": note,
        },
    )


def _load_acled_filtered(
    acled_path: Path,
    as_of_date: str,
    lookback_months: int,
    included_event_types: list[str],
) -> pd.DataFrame:
    import pandas as pd
    from pandas.tseries.offsets import DateOffset

    raw = pd.read_csv(acled_path)
    req = ["latitude", "longitude", "event_date", "event_type"]
    missing = [c for c in req if c not in raw.columns]
    if missing:
        raise ValueError(f"Missing ACLED columns: {missing}")

    as_of = pd.to_datetime(as_of_date)
    window_start = (as_of - DateOffset(months=int(lookback_months))) + pd.Timedelta(days=1)

    df = raw.copy()
    df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce")
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = df.dropna(subset=["event_date", "latitude", "longitude", "event_type"])
    df = df[df["latitude"].between(-90, 90) & df["longitude"].between(-180, 180)]
    df = df[(df["event_date"] >= window_start) & (df["event_date"] <= as_of)]
    df = df[df["event_type"].isin(included_event_types)]
    return df


def run_batch_preflight(
    readiness: pd.DataFrame,
    admin_path: Path,
    sample_year: int,
    sample_month: int,
    cds_buffer_deg: float = 0.25,
    flood_datetime: str = "2025-01-01/2025-01-31",
    flood_mode: str = "extents",
    flood_select: str = "mosaic",
    out_dir: Path = Path("./outputs/batch/preflight"),
    iso3_field: str = "iso3",
    included_violence_types: list[str] | None = None,
) -> dict[str, Any]:
    if readiness.empty:
        return {"rows": [], "summary": {}}

    included = included_violence_types or [
        "Battles",
        "Explosions/Remote violence",
        "Violence against civilians",
        "Riots",
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    report_rows: list[dict[str, Any]] = []
    total_tasks = int(len(readiness))
    status_path = out_dir / "batch_preflight_status.json"
    run_started_utc = _now_utc()
    _write_status(
        status_path,
        {
            "status": "RUNNING",
            "started_utc": run_started_utc,
            "completed_tasks": 0,
            "total_tasks": total_tasks,
            "pct_complete": 0.0,
            "current_task": None,
            "last_updated_utc": _now_utc(),
            "note": "Batch preflight started.",
        },
    )
    _write_partial_reports(out_dir, report_rows=[], total_tasks=total_tasks)

    for i, (_, row) in enumerate(readiness.iterrows(), start=1):
        base = row.to_dict()
        iso3 = str(row["iso3"]).upper()
        task_id = int(row["task_id"])
        _update_task_status(
            status_path=status_path,
            run_started_utc=run_started_utc,
            total_tasks=total_tasks,
            completed_tasks=i - 1,
            task_id=task_id,
            iso3=iso3,
            as_of_date=str(row.get("as_of_date")),
            target_adm_level=int(row.get("target_adm_level", 2)),
            note="Starting country preflight checks.",
        )

        # Default all checks to skipped unless readiness allows them.
        result = {
            **base,
            "spei_preflight_status": "SKIP",
            "spei_download_source": None,
            "spei_coverage_pct": None,
            "spei_full_coverage": None,
            "utci_preflight_status": "SKIP",
            "utci_download_source": None,
            "utci_coverage_pct": None,
            "utci_full_coverage": None,
            "flood_preflight_status": "SKIP",
            "flood_coverage_pct": None,
            "flood_full_coverage": None,
            "violence_preflight_status": "SKIP",
            "violence_event_count": None,
            "violence_event_bbox_coverage_pct": None,
            "violence_events_inside_admin": None,
            "preflight_issues": "",
        }

        issues: list[str] = []

        try:
            admin_layer = str(row["admin_layer"])
            _update_task_status(
                status_path=status_path,
                run_started_utc=run_started_utc,
                total_tasks=total_tasks,
                completed_tasks=i - 1,
                task_id=task_id,
                iso3=iso3,
                as_of_date=str(row.get("as_of_date")),
                target_adm_level=int(row.get("target_adm_level", 2)),
                note=f"Loading admin context ({admin_layer}).",
            )
            ctx = prepare_country_admin_context(
                iso3=iso3,
                admin_path=admin_path,
                admin_layer=admin_layer,
                iso3_field=iso3_field,
                buffer_km=0.0,
                cds_buffer_deg=cds_buffer_deg,
            )
            admin_bounds = ctx["admin_bounds_wsen"]
            country_dir = out_dir / f"task_{task_id:04d}_{iso3}"
            country_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            result["preflight_issues"] = f"admin_context_error:{exc}"
            report_rows.append(result)
            continue

        # WorldPop must be present from readiness checks.
        wp_path = Path(str(row["worldpop_path"]))

        # SPEI
        if bool(row.get("can_run_spei", False)):
            try:
                _update_task_status(
                    status_path=status_path,
                    run_started_utc=run_started_utc,
                    total_tasks=total_tasks,
                    completed_tasks=i - 1,
                    task_id=task_id,
                    iso3=iso3,
                    as_of_date=str(row.get("as_of_date")),
                    target_adm_level=int(row.get("target_adm_level", 2)),
                    note="Running SPEI preflight check.",
                )
                spei_req = spei_sample_request(sample_year, sample_month, ctx["cds_area_nwse"])
                spei_zip = country_dir / f"{iso3}_spei_{sample_year}{sample_month:02d}.zip"
                spei_pre_exists = spei_zip.exists() and spei_zip.stat().st_size > 0
                spei = run_cds_single_month_check(
                    dataset="derived-drought-historical-monthly",
                    request=spei_req,
                    output_zip=spei_zip,
                )
                result["spei_download_source"] = "cache" if spei_pre_exists else "download"
                if spei.get("sample_bounds_4326"):
                    cov = bbox_coverage_report(admin_bounds, tuple(spei["sample_bounds_4326"]))
                    result["spei_coverage_pct"] = float(cov["coverage_pct"])
                    result["spei_full_coverage"] = bool(cov["full_coverage"])
                    result["spei_preflight_status"] = "PASS" if cov["full_coverage"] else "WARN"
                else:
                    result["spei_preflight_status"] = "FAIL"
                    issues.append("spei_sample_missing_bounds")
            except Exception as exc:
                result["spei_preflight_status"] = "FAIL"
                issues.append(f"spei_error:{exc}")

        # UTCI
        if bool(row.get("can_run_utci", False)):
            try:
                _update_task_status(
                    status_path=status_path,
                    run_started_utc=run_started_utc,
                    total_tasks=total_tasks,
                    completed_tasks=i - 1,
                    task_id=task_id,
                    iso3=iso3,
                    as_of_date=str(row.get("as_of_date")),
                    target_adm_level=int(row.get("target_adm_level", 2)),
                    note="Running UTCI preflight check.",
                )
                utci_req = utci_sample_request(sample_year, sample_month, ctx["cds_area_nwse"])
                utci_zip = country_dir / f"{iso3}_utci_{sample_year}{sample_month:02d}.zip"
                utci_pre_exists = utci_zip.exists() and utci_zip.stat().st_size > 0
                utci = run_cds_single_month_check(
                    dataset="derived-utci-historical",
                    request=utci_req,
                    output_zip=utci_zip,
                )
                result["utci_download_source"] = "cache" if utci_pre_exists else "download"
                if utci.get("sample_bounds_4326"):
                    cov = bbox_coverage_report(admin_bounds, tuple(utci["sample_bounds_4326"]))
                    result["utci_coverage_pct"] = float(cov["coverage_pct"])
                    result["utci_full_coverage"] = bool(cov["full_coverage"])
                    result["utci_preflight_status"] = "PASS" if cov["full_coverage"] else "WARN"
                else:
                    result["utci_preflight_status"] = "FAIL"
                    issues.append("utci_sample_missing_bounds")
            except Exception as exc:
                result["utci_preflight_status"] = "FAIL"
                issues.append(f"utci_error:{exc}")

        # Flood
        if bool(row.get("can_run_flood", False)):
            try:
                _update_task_status(
                    status_path=status_path,
                    run_started_utc=run_started_utc,
                    total_tasks=total_tasks,
                    completed_tasks=i - 1,
                    task_id=task_id,
                    iso3=iso3,
                    as_of_date=str(row.get("as_of_date")),
                    target_adm_level=int(row.get("target_adm_level", 2)),
                    note="Running flood preflight check.",
                )
                if flood_mode == "extents":
                    flood = run_flood_stac_extent_check(
                        iso3=iso3,
                        admin_gdf=ctx["admin_gdf"],
                        admin_bounds_wsen=admin_bounds,
                        datetime_range=flood_datetime,
                    )
                    cov = float(flood.get("union_bbox_coverage_pct", 0.0))
                    full = bool(flood.get("union_full_coverage", False))
                else:
                    # asset mode should be used via existing single-country coverage script.
                    cov = None
                    full = None
                    issues.append("flood_asset_mode_not_implemented_in_batch_preflight")
                result["flood_coverage_pct"] = cov
                result["flood_full_coverage"] = full
                if full is True:
                    result["flood_preflight_status"] = "PASS"
                elif full is False:
                    result["flood_preflight_status"] = "WARN"
                else:
                    result["flood_preflight_status"] = "SKIP"
            except Exception as exc:
                result["flood_preflight_status"] = "FAIL"
                issues.append(f"flood_error:{exc}")

        # Violence
        if bool(row.get("can_run_violence", False)):
            try:
                _update_task_status(
                    status_path=status_path,
                    run_started_utc=run_started_utc,
                    total_tasks=total_tasks,
                    completed_tasks=i - 1,
                    task_id=task_id,
                    iso3=iso3,
                    as_of_date=str(row.get("as_of_date")),
                    target_adm_level=int(row.get("target_adm_level", 2)),
                    note="Running violence preflight check.",
                )
                acled_path = Path(str(row["acled_path"]))
                acled_df = _load_acled_filtered(
                    acled_path=acled_path,
                    as_of_date=str(row["as_of_date"]),
                    lookback_months=int(row["lookback_months"]),
                    included_event_types=included,
                )
                result["violence_event_count"] = int(len(acled_df))
                if not acled_df.empty:
                    ev = gpd.GeoDataFrame(
                        acled_df,
                        geometry=gpd.points_from_xy(acled_df["longitude"], acled_df["latitude"]),
                        crs="EPSG:4326",
                    )
                    events_bounds = tuple(float(v) for v in ev.total_bounds)
                    cov = bbox_coverage_report(admin_bounds, events_bounds)
                    inside = int(ev.within(ctx["admin_gdf"].to_crs("EPSG:4326").geometry.union_all()).sum())
                    result["violence_event_bbox_coverage_pct"] = float(cov["coverage_pct"])
                    result["violence_events_inside_admin"] = inside
                    result["violence_preflight_status"] = "PASS" if inside > 0 else "WARN"
                else:
                    result["violence_preflight_status"] = "FAIL"
                    issues.append("violence_no_events_after_filters")
            except Exception as exc:
                result["violence_preflight_status"] = "FAIL"
                issues.append(f"violence_error:{exc}")

        # WorldPop coverage checkpoint
        try:
            _update_task_status(
                status_path=status_path,
                run_started_utc=run_started_utc,
                total_tasks=total_tasks,
                completed_tasks=i - 1,
                task_id=task_id,
                iso3=iso3,
                as_of_date=str(row.get("as_of_date")),
                target_adm_level=int(row.get("target_adm_level", 2)),
                note="Running WorldPop coverage check.",
            )
            wp_cov = check_worldpop_coverage(admin_bounds, wp_path)
            result["worldpop_coverage_pct"] = float(wp_cov["coverage_pct"])
            result["worldpop_full_coverage"] = bool(wp_cov["full_coverage"])
        except Exception as exc:
            result["worldpop_coverage_pct"] = None
            result["worldpop_full_coverage"] = False
            issues.append(f"worldpop_coverage_error:{exc}")

        result["preflight_issues"] = "; ".join(issues)
        report_rows.append(result)
        _write_partial_reports(out_dir, report_rows, total_tasks=total_tasks)
        _write_status(
            status_path,
            {
                "status": "RUNNING",
                "started_utc": run_started_utc,
                "completed_tasks": i,
                "total_tasks": total_tasks,
                "pct_complete": float((i / total_tasks) * 100.0) if total_tasks else 100.0,
                "current_task": {
                    "task_id": task_id,
                    "iso3": iso3,
                },
                "last_updated_utc": _now_utc(),
                "note": "Task completed and partial reports updated.",
            },
        )

    report_df = pd.DataFrame(report_rows)

    # Persist canonical outputs.
    out_csv = out_dir / "batch_preflight_report.csv"
    out_json = out_dir / "batch_preflight_report.json"
    report_df.to_csv(out_csv, index=False)
    out_json.write_text(
        json.dumps(
            {
                "n_tasks": int(len(report_df)),
                "reports": report_df.to_dict(orient="records"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = {
        "n_tasks": int(len(report_df)),
        "n_ready_all": int(report_df.get("readiness_ok_all", pd.Series(dtype=bool)).fillna(False).sum()),
        "spei_fail": int((report_df.get("spei_preflight_status") == "FAIL").sum()),
        "utci_fail": int((report_df.get("utci_preflight_status") == "FAIL").sum()),
        "flood_fail": int((report_df.get("flood_preflight_status") == "FAIL").sum()),
        "violence_fail": int((report_df.get("violence_preflight_status") == "FAIL").sum()),
    }
    _write_status(
        status_path,
        {
            "status": "COMPLETED",
            "started_utc": run_started_utc,
            "completed_tasks": total_tasks,
            "total_tasks": total_tasks,
            "pct_complete": 100.0,
            "current_task": None,
            "last_updated_utc": _now_utc(),
            "note": "Batch preflight completed.",
            "summary": summary,
        },
    )
    return {
        "summary": summary,
        "report_csv": str(out_csv),
        "report_json": str(out_json),
        "status_json": str(status_path),
        "report": report_df,
    }
