from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_ISO3_ALIASES: dict[str, str] = {
    "LEB": "LBN",  # common typo in batch manifests
}


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except Exception:
        return False


def _clean_scalar(value: Any) -> str:
    if _is_missing(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _normalize_iso3(value: Any, alias_map: dict[str, str]) -> tuple[str, str | None]:
    raw = _clean_scalar(value).upper()
    if not raw:
        return "", "ISO3 is empty"
    mapped = alias_map.get(raw, raw)
    if len(mapped) != 3 or not mapped.isalpha():
        return mapped, f"ISO3 '{raw}' is not a valid 3-letter code"
    return mapped, None


def _parse_date(value: Any) -> tuple[str, str | None]:
    raw = _clean_scalar(value)
    if not raw:
        return "", "as_of_date is empty"
    try:
        return date.fromisoformat(raw).isoformat(), None
    except Exception:
        return raw, f"as_of_date '{raw}' is not YYYY-MM-DD"


def _parse_lookback(value: Any) -> tuple[int | None, str | None]:
    try:
        months = int(_clean_scalar(value))
    except Exception:
        return None, f"lookback '{value}' is not an integer"
    if months < 1:
        return None, f"lookback '{value}' must be >= 1"
    return months, None


def _parse_admin_level(value: Any, default_admin_level: int) -> tuple[int | None, str | None]:
    if _clean_scalar(value) == "":
        level = int(default_admin_level)
    else:
        try:
            level = int(_clean_scalar(value))
        except Exception:
            return None, f"admin_level '{value}' is not an integer"
    if level < 0 or level > 3:
        return None, f"admin_level '{level}' must be between 0 and 3"
    return level, None


def load_batch_manifest(
    manifest_path: str | Path,
    default_admin_level: int = 2,
    iso3_aliases: dict[str, str] | None = None,
    iso_lookup_path: str | Path | None = "./data/violence/iso_country-codes.csv",
) -> pd.DataFrame:
    """Load and normalize a batch manifest.

    Required columns:
    - ISO3
    - as_of_date
    - lookback

    Optional columns:
    - admin_level (defaults to default_admin_level when missing/blank)
    - m49_code (if missing, resolved from iso_lookup_path when available)
    """

    path = Path(manifest_path)
    if not path.exists():
        raise FileNotFoundError(f"Batch manifest not found: {path.resolve()}")

    aliases = {k.upper(): v.upper() for k, v in (iso3_aliases or DEFAULT_ISO3_ALIASES).items()}

    df = pd.read_csv(path, encoding="utf-8-sig")
    df = df.dropna(how="all").reset_index(drop=True)
    required_cols = {"ISO3", "as_of_date", "lookback"}
    missing = sorted(required_cols - set(df.columns))
    if missing:
        raise ValueError(f"Missing required manifest columns: {missing}")

    if "admin_level" not in df.columns:
        df["admin_level"] = default_admin_level
    if "m49_code" not in df.columns:
        df["m49_code"] = None

    iso_to_m49: dict[str, str] = {}
    iso_to_country: dict[str, str] = {}
    if iso_lookup_path is not None:
        lookup = Path(iso_lookup_path)
        if lookup.exists():
            lk = pd.read_csv(lookup, sep=";", encoding="utf-8-sig")
            req = {"ISO-alpha3 Code", "M49 Code", "Country or Area"}
            if req.issubset(set(lk.columns)):
                sub = lk[list(req)].dropna(subset=["ISO-alpha3 Code", "M49 Code"]).copy()
                sub["ISO-alpha3 Code"] = sub["ISO-alpha3 Code"].astype(str).str.upper()
                sub["M49 Code"] = sub["M49 Code"].astype(str).str.strip()
                iso_to_m49 = dict(zip(sub["ISO-alpha3 Code"], sub["M49 Code"]))
                iso_to_country = dict(zip(sub["ISO-alpha3 Code"], sub["Country or Area"].astype(str)))

    out_rows: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        iso3_norm, iso3_err = _normalize_iso3(row.get("ISO3"), aliases)
        as_of_date, date_err = _parse_date(row.get("as_of_date"))
        lookback_months, lookback_err = _parse_lookback(row.get("lookback"))
        target_adm_level, adm_err = _parse_admin_level(row.get("admin_level"), default_admin_level)
        m49_raw = _clean_scalar(row.get("m49_code"))
        m49_lookup = iso_to_m49.get(iso3_norm, "")
        m49_code = m49_raw or m49_lookup
        m49_err = None
        if not m49_code:
            m49_err = f"m49_code missing for ISO3 '{iso3_norm}'"
        elif not str(m49_code).strip().isdigit():
            m49_err = f"m49_code '{m49_code}' is not numeric"

        errors = [e for e in [iso3_err, date_err, lookback_err, adm_err, m49_err] if e]
        iso3_input = _clean_scalar(row.get("ISO3")).upper()
        out_rows.append(
            {
                "task_id": idx + 1,
                "iso3_input": iso3_input,
                "iso3": iso3_norm,
                "iso3_alias_applied": iso3_input != iso3_norm,
                "country_name": iso_to_country.get(iso3_norm, ""),
                "m49_code": str(m49_code),
                "as_of_date": as_of_date,
                "lookback_months": lookback_months,
                "target_adm_level": target_adm_level,
                "is_valid_manifest": len(errors) == 0,
                "manifest_errors": "; ".join(errors),
            }
        )

    normalized = pd.DataFrame(out_rows)
    return normalized
