from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Iterable
from urllib.request import Request, urlopen

import geopandas as gpd
import pandas as pd
import yaml

from ...config import RunConfig, build_run_paths
from .pipeline import RunInputs, run_pipeline, validate_inputs


REQUIRED_COLUMNS = {"ISO", "Name", "Admin", "Date"}
ISO3_ALIASES = {"LEB": "LBN"}
DENOMINATOR_TOLERANCE_OVERRIDES = {"GRD": 0.05, "VCT": 0.05, "PAK": 0.025}
WORLDPOP_URL = (
    "https://data.worldpop.org/GIS/Population/Global_2015_2030/"
    "R2025A/2025/{ISO3}/v1/100m/constrained/"
    "{iso3}_pop_2025_CN_100m_R2025A_v1.tif"
)


def read_bulk_table(path: Path) -> pd.DataFrame:
    table = pd.read_csv(path, encoding="utf-8-sig")
    missing = REQUIRED_COLUMNS - set(table.columns)
    if missing:
        raise ValueError(f"Bulk country table is missing columns: {sorted(missing)}")
    table = table.loc[:, ["ISO", "Name", "Admin", "Date"]].copy()
    table["ISO"] = table["ISO"].astype(str).str.strip().str.upper()
    table["Name"] = table["Name"].astype(str).str.strip()
    table["Admin"] = pd.to_numeric(table["Admin"], errors="raise").astype(int)
    table["Date"] = pd.to_datetime(table["Date"], errors="raise").dt.date.astype(str)
    if table["ISO"].duplicated().any():
        duplicates = sorted(table.loc[table["ISO"].duplicated(False), "ISO"].unique())
        raise ValueError(f"Bulk country table contains duplicate ISO codes: {duplicates}")
    if not table["ISO"].str.fullmatch(r"[A-Z]{3}").all():
        raise ValueError("Every ISO value must contain exactly three letters")
    if (table["Admin"] < 0).any():
        raise ValueError("Admin levels must be non-negative")
    return table


def _worldpop_filename(iso3: str) -> str:
    return f"{iso3.lower()}_pop_2025_CN_100m_R2025A_v1.tif"


def find_worldpop(iso3: str, search_dirs: Iterable[Path]) -> Path | None:
    filename = _worldpop_filename(iso3)
    for directory in search_dirs:
        candidate = Path(directory) / filename
        if candidate.is_file():
            return candidate
    return None


def download_worldpop(
    iso3: str,
    output_dir: Path,
    timeout: float = 300,
    attempts: int = 3,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / _worldpop_filename(iso3)
    if destination.is_file():
        return destination
    url = WORLDPOP_URL.format(ISO3=iso3, iso3=iso3.lower())
    partial = destination.with_suffix(destination.suffix + ".part")
    last_error = None
    for attempt in range(attempts):
        offset = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": "wia-hi06/0.1 bulk runner"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = Request(url, headers=headers)
        try:
            with urlopen(request, timeout=timeout) as response:
                append = offset > 0 and getattr(response, "status", None) == 206
                with partial.open("ab" if append else "wb") as stream:
                    while chunk := response.read(1024 * 1024):
                        stream.write(chunk)
            partial.replace(destination)
            break
        except Exception as error:
            last_error = error
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    else:
        raise RuntimeError(
            f"WorldPop download failed for {iso3} after {attempts} attempts: {last_error}"
        ) from last_error
    metadata = {
        "source_url": url,
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "iso3": iso3,
        "reference_year": 2025,
        "product": "WorldPop R2025A constrained 100m v1",
    }
    destination.with_suffix(".source.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    return destination


def prepare_admin(
    iso3: str,
    level: int,
    archive_path: Path,
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{iso3.lower()}_adm{level}.gpkg"
    if destination.is_file():
        existing = gpd.read_file(destination)
        if not existing.empty and f"adm{level}_pcode" in existing.columns:
            return destination
        destination.unlink()
    source = f"zip://{archive_path.resolve()}"
    admin = gpd.read_file(source, layer=f"admin{level}", where=f"iso3 = '{iso3}'")
    if admin.empty:
        raise ValueError(f"No admin-{level} features found for {iso3}")
    pcode = f"adm{level}_pcode"
    if pcode not in admin or admin[pcode].isna().any() or admin[pcode].duplicated().any():
        raise ValueError(f"Admin-{level} P-codes for {iso3} are missing or not unique")
    admin.to_file(destination, layer=f"admin{level}", driver="GPKG")
    return destination


def write_country_config(iso3: str, level: int, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{iso3.lower()}_admin{level}.yml"
    fields = {f"adm{item}_pcode": f"adm{item}_pcode" for item in range(level + 1)}
    fields.update(
        {
            f"adm{level}_name_en": f"adm{level}_name",
            f"adm{level}_name_local": f"adm{level}_name1",
            "iso3": "iso3",
        }
    )
    config = {"admin": {"level": level, "layer": f"admin{level}", "fields": fields}}
    if iso3 in DENOMINATOR_TOLERANCE_OVERRIDES:
        config["population"] = {"max_unassigned_fraction": DENOMINATOR_TOLERANCE_OVERRIDES[iso3]}
    destination.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return destination


def _country_output(output_root: Path, iso3: str, reference_date: str, level: int) -> Path:
    run_config = RunConfig(
        hazard="cyclone",
        iso3=iso3,
        as_of_date=reference_date,
        output_root=output_root,
        target_adm_level=level,
    )
    return build_run_paths(run_config)["base"]


def _completed_summary(output_dir: Path, iso3: str, reference_date: str) -> dict | None:
    manifest_path = output_dir / "run_metadata.json"
    table_path = output_dir / "tables" / f"HI06_{iso3}_{reference_date}.csv"
    if not manifest_path.is_file() or not table_path.is_file():
        return None
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def run_bulk(
    countries_path: Path,
    ibtracs_path: Path,
    admin_archive: Path,
    worldpop_search_dirs: list[Path],
    worldpop_download_dir: Path,
    inputs_dir: Path,
    out_dir: Path,
    *,
    download_missing_worldpop: bool = False,
    gdacs_auto: bool = False,
    resume: bool = False,
) -> Path:
    table = read_bulk_table(countries_path)
    summary_dir = out_dir / "batch" / "cyclone"
    summary_dir.mkdir(parents=True, exist_ok=True)
    summary_path = summary_dir / "HI06_bulk_summary.csv"
    rows = []

    for record in table.to_dict("records"):
        started = time.monotonic()
        input_iso3 = record["ISO"]
        iso3 = ISO3_ALIASES.get(input_iso3, input_iso3)
        level = int(record["Admin"])
        reference_date = record["Date"]
        row = {
            "input_iso3": input_iso3,
            "iso3": iso3,
            "iso_alias_applied": input_iso3 != iso3,
            "name": record["Name"],
            "admin_level": level,
            "reference_date": reference_date,
            "status": "running",
            "reused_existing": False,
            "output_dir": None,
            "pct_affected": None,
            "pop_affected": None,
            "pop_total": None,
            "candidate_storms": None,
            "gdacs_fallback": None,
            "population_assigned_fraction": None,
            "denominator_tolerance": DENOMINATOR_TOLERANCE_OVERRIDES.get(iso3, 0.02),
            "error": None,
            "elapsed_seconds": None,
        }
        try:
            country_output = _country_output(out_dir, iso3, reference_date, level)
            previous = _completed_summary(country_output, iso3, reference_date) if resume else None
            if previous is not None:
                manifest = previous
                row["status"] = "success"
                row["reused_existing"] = True
            else:
                population = find_worldpop(iso3, [*worldpop_search_dirs, worldpop_download_dir])
                if population is None and download_missing_worldpop:
                    population = download_worldpop(iso3, worldpop_download_dir)
                if population is None:
                    raise FileNotFoundError(f"No 2025 WorldPop raster found for {iso3}")
                admin_path = prepare_admin(iso3, level, admin_archive, inputs_dir / "admin")
                config_path = write_country_config(iso3, level, inputs_dir / "bulk_config")
                inputs = RunInputs(
                    iso3=iso3,
                    window_end=reference_date,
                    ibtracs=ibtracs_path,
                    worldpop=population,
                    admin=admin_path,
                    out=out_dir,
                    lookback_months=12,
                    config=config_path,
                    gdacs_auto=gdacs_auto,
                )
                validate_inputs(inputs)
                run_pipeline(inputs)
                manifest = _completed_summary(country_output, iso3, reference_date)
                if manifest is None:
                    raise RuntimeError("Pipeline completed without a readable manifest and result CSV")
                row["status"] = "success"
            country = manifest["country_summary"]
            result_table = pd.read_csv(country_output / "tables" / f"HI06_{iso3}_{reference_date}.csv")
            row.update(
                {
                    "output_dir": str(country_output),
                    "pct_affected": country["pct_affected"],
                    "pop_affected": country["pop_affected"],
                    "pop_total": country["pop_total"],
                    "candidate_storms": manifest["qa"]["candidate_storms"],
                    "gdacs_fallback": bool(result_table["flag_method_fallback"].any()),
                    "population_assigned_fraction": country["population_assigned_fraction"],
                }
            )
        except Exception as error:
            row["status"] = "failed"
            row["error"] = f"{type(error).__name__}: {error}"
        row["elapsed_seconds"] = round(time.monotonic() - started, 3)
        rows.append(row)
        pd.DataFrame(rows).to_csv(summary_path, index=False)
    return summary_path
