from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd


@dataclass
class AdminLayerSummary:
    exists: bool
    iso3_feature_counts: dict[str, int]
    missing_required_columns: list[str]


def worldpop_path_for_iso3(
    iso3: str,
    worldpop_dir: Path,
    worldpop_template: str = "{iso3_lower}_pop_2025_CN_100m_R2025A_v1.tif",
) -> Path:
    return worldpop_dir / worldpop_template.format(
        iso3=iso3.upper(),
        iso3_lower=iso3.lower(),
        iso3_upper=iso3.upper(),
    )


def _window_start_end(as_of_date: str, lookback_months: int) -> tuple[str, str]:
    as_of = pd.to_datetime(as_of_date)
    start = (as_of - pd.DateOffset(months=int(lookback_months))) + pd.Timedelta(days=1)
    return start.date().isoformat(), as_of.date().isoformat()


def acled_filename_for_iso3(
    iso3: str,
    as_of_date: str,
    lookback_months: int,
) -> str:
    start, end = _window_start_end(as_of_date=as_of_date, lookback_months=lookback_months)
    return f"acled_{iso3.lower()}_{start.replace('-', '')}-{end.replace('-', '')}.csv"


def acled_path_for_iso3(
    iso3: str,
    as_of_date: str,
    lookback_months: int,
    acled_dir: Path,
) -> Path:
    expected = acled_dir / acled_filename_for_iso3(
        iso3=iso3,
        as_of_date=as_of_date,
        lookback_months=lookback_months,
    )
    if expected.exists():
        return expected

    # Legacy fallback patterns used in earlier notebook iterations.
    start, end = _window_start_end(as_of_date=as_of_date, lookback_months=lookback_months)
    legacy_candidates = [
        acled_dir / f"acled_{iso3.lower()}_{start.replace('-', '')}_{end}.csv",
        acled_dir / f"acled_{iso3.lower()}_{start.replace('-', '')}_{end.replace('-', '')}.csv",
    ]
    for p in legacy_candidates:
        if p.exists():
            return p

    # Last-resort fallback to any country file.
    candidates = sorted(acled_dir.glob(f"acled_{iso3.lower()}_*.csv"))
    if candidates:
        return candidates[-1]
    return expected


def _find_bulk_iso_column(df: pd.DataFrame) -> str | None:
    candidates = [
        "iso3",
        "iso",
        "country_iso",
        "country_code",
        "event_iso",
    ]
    lower = {c.lower(): c for c in df.columns}
    for c in candidates:
        if c in lower:
            return lower[c]
    return None


def ensure_country_acled_file(
    iso3: str,
    m49_code: str | int | None,
    as_of_date: str,
    lookback_months: int,
    acled_dir: Path,
    bulk_acled_path: Path | None,
    bulk_iso_column: str = "iso",
) -> Path:
    target = acled_dir / acled_filename_for_iso3(
        iso3=iso3,
        as_of_date=as_of_date,
        lookback_months=lookback_months,
    )
    if target.exists() and target.stat().st_size > 0:
        return target

    if bulk_acled_path is None or not bulk_acled_path.exists():
        return acled_path_for_iso3(iso3, as_of_date, lookback_months, acled_dir)

    bulk = pd.read_csv(bulk_acled_path)
    iso_col = bulk_iso_column if bulk_iso_column in bulk.columns else _find_bulk_iso_column(bulk)
    if iso_col is None or "event_date" not in bulk.columns:
        return acled_path_for_iso3(iso3, as_of_date, lookback_months, acled_dir)
    if m49_code is None or str(m49_code).strip() == "":
        return acled_path_for_iso3(iso3, as_of_date, lookback_months, acled_dir)

    start, end = _window_start_end(as_of_date=as_of_date, lookback_months=lookback_months)
    df = bulk.copy()
    # ACLED bulk file uses M49 code in 'iso'. Compare as integers when possible.
    target_m49 = str(m49_code).strip()
    target_m49_int = int(target_m49) if target_m49.isdigit() else None
    df[iso_col] = pd.to_numeric(df[iso_col], errors="coerce")
    df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce")
    start_dt = pd.to_datetime(start)
    end_dt = pd.to_datetime(end)
    if target_m49_int is not None:
        df = df[(df[iso_col] == target_m49_int)]
    else:
        # Fallback for uncommon non-numeric code representations.
        df = bulk.copy()
        df[iso_col] = df[iso_col].astype(str).str.strip()
        df["event_date"] = pd.to_datetime(df["event_date"], errors="coerce")
        df = df[(df[iso_col] == target_m49)]
    df = df[(df["event_date"] >= start_dt) & (df["event_date"] <= end_dt)]

    if df.empty:
        return acled_path_for_iso3(iso3, as_of_date, lookback_months, acled_dir)

    acled_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(target, index=False)
    return target


def _read_admin_layer(admin_path: Path, layer: str) -> gpd.GeoDataFrame:
    if str(admin_path).lower().endswith(".zip"):
        return gpd.read_file(f"zip://{admin_path.resolve()}", layer=layer)
    try:
        return gpd.read_file(admin_path, layer=layer)
    except Exception:
        return gpd.read_file(admin_path)


def build_admin_layer_summary(
    admin_path: Path,
    target_adm_levels: set[int],
    iso3_field: str = "iso3",
) -> dict[int, AdminLayerSummary]:
    summaries: dict[int, AdminLayerSummary] = {}
    for lvl in sorted(target_adm_levels):
        layer = f"admin{lvl}"
        try:
            gdf = _read_admin_layer(admin_path, layer=layer)
        except Exception:
            summaries[lvl] = AdminLayerSummary(
                exists=False,
                iso3_feature_counts={},
                missing_required_columns=[iso3_field, "geometry"],
            )
            continue

        missing_cols = [c for c in [iso3_field, "geometry"] if c not in gdf.columns]
        iso_counts: dict[str, int] = {}
        if not missing_cols:
            valid = gdf.dropna(subset=[iso3_field, "geometry"]).copy()
            valid = valid[valid.geometry.is_valid]
            iso_counts = valid[iso3_field].astype(str).str.upper().value_counts().to_dict()

        summaries[lvl] = AdminLayerSummary(
            exists=True,
            iso3_feature_counts=iso_counts,
            missing_required_columns=missing_cols,
        )
    return summaries


def evaluate_batch_readiness(
    tasks: pd.DataFrame,
    admin_path: Path,
    worldpop_dir: Path,
    acled_dir: Path = Path("./data/violence"),
    bulk_acled_path: Path | None = None,
    create_country_acled_from_bulk: bool = True,
    bulk_acled_iso_column: str = "iso",
    iso3_field: str = "iso3",
    worldpop_template: str = "{iso3_lower}_pop_2025_CN_100m_R2025A_v1.tif",
) -> pd.DataFrame:
    if tasks.empty:
        return tasks.copy()

    required_cols = {
        "task_id",
        "iso3",
        "as_of_date",
        "lookback_months",
        "target_adm_level",
        "is_valid_manifest",
    }
    missing = sorted(required_cols - set(tasks.columns))
    if missing:
        raise ValueError(f"Task dataframe missing required columns: {missing}")

    levels = set(pd.to_numeric(tasks["target_adm_level"], errors="coerce").dropna().astype(int).tolist())
    admin_summary = build_admin_layer_summary(
        admin_path=admin_path, target_adm_levels=levels, iso3_field=iso3_field
    )

    rows: list[dict[str, Any]] = []
    for _, row in tasks.iterrows():
        iso3 = str(row["iso3"]).upper()
        if not bool(row["is_valid_manifest"]):
            issues = [str(row.get("manifest_errors") or "manifest invalid")]
            out = row.to_dict()
            out.update(
                {
                    "admin_layer": "",
                    "admin_layer_exists": False,
                    "admin_has_required_cols": False,
                    "admin_feature_count": 0,
                    "worldpop_path": "",
                    "worldpop_exists": False,
                    "acled_path": "",
                    "acled_exists": False,
                    "can_run_spei": False,
                    "can_run_utci": False,
                    "can_run_flood": False,
                    "can_run_violence": False,
                    "readiness_ok_all": False,
                    "readiness_issues": "; ".join(issues),
                }
            )
            rows.append(out)
            continue

        level = int(row["target_adm_level"])

        wp_path = worldpop_path_for_iso3(iso3, worldpop_dir, worldpop_template=worldpop_template)

        if create_country_acled_from_bulk:
            acled_path = ensure_country_acled_file(
                iso3=iso3,
                m49_code=row.get("m49_code"),
                as_of_date=str(row["as_of_date"]),
                lookback_months=int(row["lookback_months"]),
                acled_dir=acled_dir,
                bulk_acled_path=bulk_acled_path,
                bulk_iso_column=bulk_acled_iso_column,
            )
        else:
            acled_path = acled_path_for_iso3(
                iso3,
                as_of_date=str(row["as_of_date"]),
                lookback_months=int(row["lookback_months"]),
                acled_dir=acled_dir,
            )

        admin_lvl = admin_summary.get(level)
        admin_layer_exists = bool(admin_lvl and admin_lvl.exists)
        admin_has_required_cols = bool(admin_lvl and len(admin_lvl.missing_required_columns) == 0)
        admin_feature_count = int((admin_lvl.iso3_feature_counts.get(iso3, 0) if admin_lvl else 0))
        admin_iso_ok = admin_feature_count > 0

        worldpop_exists = wp_path.exists()
        acled_exists = acled_path.exists()

        # Hard gates by pipeline.
        can_common = (
            bool(row["is_valid_manifest"])
            and worldpop_exists
            and admin_layer_exists
            and admin_has_required_cols
            and admin_iso_ok
        )
        can_run_spei = can_common
        can_run_utci = can_common
        can_run_flood = can_common
        can_run_violence = can_common and acled_exists

        issues: list[str] = []
        if not bool(row["is_valid_manifest"]):
            issues.append(str(row.get("manifest_errors") or "manifest invalid"))
        if not worldpop_exists:
            issues.append("missing_worldpop")
        if not admin_layer_exists:
            issues.append(f"missing_admin_layer_admin{level}")
        elif not admin_has_required_cols:
            issues.append(f"admin_layer_missing_columns:{','.join(admin_lvl.missing_required_columns)}")
        elif not admin_iso_ok:
            issues.append(f"iso3_not_found_in_admin{level}")
        if not acled_exists:
            issues.append("missing_acled_csv")

        out = row.to_dict()
        out.update(
            {
                "admin_layer": f"admin{level}",
                "admin_layer_exists": admin_layer_exists,
                "admin_has_required_cols": admin_has_required_cols,
                "admin_feature_count": admin_feature_count,
                "worldpop_path": str(wp_path),
                "worldpop_exists": worldpop_exists,
                "acled_path": str(acled_path),
                "acled_exists": acled_exists,
                "can_run_spei": can_run_spei,
                "can_run_utci": can_run_utci,
                "can_run_flood": can_run_flood,
                "can_run_violence": can_run_violence,
                "readiness_ok_all": can_run_spei and can_run_utci and can_run_flood and can_run_violence,
                "readiness_issues": "; ".join(issues),
            }
        )
        rows.append(out)

    return pd.DataFrame(rows)
