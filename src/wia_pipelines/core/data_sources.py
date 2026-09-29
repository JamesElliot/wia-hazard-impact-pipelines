"""Input-dataset provenance for ``run_metadata.json`` (the ``data_sources`` array).

Each entry records what a run was built from, in the terms a data credit needs: dataset name and
version, period and area used, access date, DOI or URL, licence and attribution wording.

Provider facts that do not change between runs (DOI, licence, attribution) live in ``REGISTRY``.
They were read from the provider's own catalogue or terms page on ``REGISTRY_VERIFIED_ON``; see
``docs/output-contract.md``. Nothing here is fetched at run time, so runs stay offline-safe.
Facts that change per run (version, access date, period, selection, checksum) are passed in.

``licence`` is descriptive, copied from the provider. It is not legal advice.

Access dates come from the retrieval, never from the run date. Files fetched by this repository's
downloaders get a ``<file>.retrieved.json`` sidecar recording the retrieval date. A file with no
sidecar has an unknown access date: the entry records ``null`` and a warning is logged.
"""

from __future__ import annotations

import json
import re
import warnings
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REGISTRY_VERIFIED_ON = "2026-09-29"
RETRIEVAL_SUFFIX = ".retrieved.json"

_COPERNICUS_CLIMATE_LICENCE_URL = (
    "https://object-store.os-api.cci2.ecmwf.int:443/cci2-prod-catalogue/licences/"
    "licence-to-use-copernicus-products/licence-to-use-copernicus-products_"
    "b4b9451f54cffa16ecef5c912c9cebd6979925a956e3fa677976e0cf198c2c18.pdf"
)
_COPERNICUS_CLIMATE_ATTRIBUTION = (
    "Generated using Copernicus Climate Change Service information {year}; where modified: "
    "Contains modified Copernicus Climate Change Service information {year}. Neither the "
    "European Commission nor ECMWF is responsible for any use that may be made of the "
    "Copernicus information or data it contains."
)

# Keys are stable identifiers used by the pipelines. Values are provider facts only.
REGISTRY: dict[str, dict[str, Any]] = {
    "era5_heat_utci": {
        "dataset": "ERA5-HEAT (UTCI)",
        "provider": "Copernicus Climate Change Service (C3S), ECMWF",
        "catalogue_id": "derived-utci-historical",
        "doi": "10.24381/cds.553b7518",
        "url": "https://cds.climate.copernicus.eu/datasets/derived-utci-historical",
        "licence": "Licence to use Copernicus Products",
        "licence_url": _COPERNICUS_CLIMATE_LICENCE_URL,
        "attribution": _COPERNICUS_CLIMATE_ATTRIBUTION,
    },
    "era5_drought_spei": {
        "dataset": "ERA5-Drought (SPEI)",
        "provider": "Copernicus Climate Change Service (C3S), ECMWF",
        "catalogue_id": "derived-drought-historical-monthly",
        "doi": "10.24381/9bea5e16",
        "url": "https://cds.climate.copernicus.eu/datasets/derived-drought-historical-monthly",
        "licence": "CC-BY-4.0",
        "licence_url": "https://spdx.org/licenses/CC-BY-4.0",
        "attribution": _COPERNICUS_CLIMATE_ATTRIBUTION,
    },
    "glofas_historical": {
        "dataset": "GloFAS historical river discharge",
        "provider": "Copernicus Emergency Management Service (CEMS), ECMWF",
        "catalogue_id": "cems-glofas-historical",
        "doi": "10.24381/cds.a4fdd6b9",
        "url": "https://ewds.climate.copernicus.eu/datasets/cems-glofas-historical",
        "licence": "CEMS-FLOODS datasets licence",
        "licence_url": (
            "https://object-store.os-api.cci2.ecmwf.int:443/cci2-prod-catalogue/licences/"
            "cems-floods/cems-floods_428a6e1019ec50b3dad9c37a90d630fab139059933a939dd5df620bfcb420cc3.pdf"
        ),
        "attribution": (
            "Generated using Copernicus Emergency Management Service information {year}; where "
            "modified: Contains modified Copernicus Emergency Management Service information {year}."
        ),
    },
    "hydrorivers": {
        "dataset": "HydroRIVERS",
        "provider": "HydroSHEDS (WWF, Lehner and Grill)",
        "catalogue_id": None,
        "doi": "10.1002/hyp.9740",  # Lehner and Grill (2013); the dataset has no DOI of its own.
        "url": "https://www.hydrosheds.org/products/hydrorivers",
        "licence": "Free for scientific, educational and commercial use under the HydroSHEDS licence",
        "licence_url": "https://data.hydrosheds.org/file/technical-documentation/HydroSHEDS_TechDoc_v1_4.pdf",
        "attribution": (
            "Lehner, B., Grill G. (2013). Global river hydrography and network routing: baseline data "
            "and new approaches to study the world's large river systems. Hydrological Processes, "
            "27(15): 2171-2186."
        ),
    },
    "gfm": {
        "dataset": "Global Flood Monitoring (GFM)",
        "provider": "Copernicus Emergency Management Service (JRC CEMS), hosted by EODC",
        "catalogue_id": "GFM",
        "doi": None,  # The STAC collection lists paper DOIs only, not a dataset DOI.
        "url": "https://stac.eodc.eu/api/v1/collections/GFM",
        "licence": "proprietary (as stated in the EODC STAC collection metadata)",
        "licence_url": "https://stac.eodc.eu/api/v1/collections/GFM",
        "attribution": None,
        "notes": (
            "The GFM terms text and attribution wording were not retrievable on "
            f"{REGISTRY_VERIFIED_ON}; confirm with JRC CEMS/EODC before publishing a credit."
        ),
    },
    "worldpop": {
        "dataset": "WorldPop Global 2015-2030 (constrained, 100 m)",
        "provider": "WorldPop, University of Southampton",
        "catalogue_id": None,
        "doi": "10.5258/SOTON/WP00839",
        "url": "https://hub.worldpop.org/doi/10.5258/SOTON/WP00839",
        "licence": "CC-BY-4.0",
        "licence_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": (
            "Bondarenko M., Priyatikanto R., Tejedor-Garavito N., et al. 2025. Constrained estimates "
            "of 2015-2030 total number of people per grid square at a resolution of 3 arc "
            "(approximately 100m at the equator) R2025A version v1. WorldPop, University of "
            "Southampton. DOI:10.5258/SOTON/WP00839"
        ),
    },
    "ibtracs": {
        "dataset": "IBTrACS",
        "provider": "NOAA National Centers for Environmental Information",
        "catalogue_id": None,
        "doi": "10.25921/82ty-9e16",
        "url": "https://www.ncei.noaa.gov/products/international-best-track-archive",
        "licence": "Full and open access (World Data Center for Meteorology policy)",
        "licence_url": "https://www.ncei.noaa.gov/products/international-best-track-archive",
        "attribution": (
            "Knapp, K. R., M. C. Kruk, D. H. Levinson, H. J. Diamond, and C. J. Neumann, 2010: The "
            "International Best Track Archive for Climate Stewardship (IBTrACS). Bulletin of the "
            "American Meteorological Society, 91, 363-376; and Gahtan, J., K. R. Knapp, C. J. "
            "Schreck, H. J. Diamond, J. P. Kossin, M. C. Kruk, 2024: International Best Track "
            "Archive for Climate Stewardship (IBTrACS) Project, Version 4r01. NOAA National "
            "Centers for Environmental Information."
        ),
    },
    "gdacs": {
        "dataset": "GDACS wind footprints (fallback)",
        "provider": "Global Disaster Alert and Coordination System (GDACS)",
        "catalogue_id": None,
        "doi": None,
        "url": "https://www.gdacs.org",
        "licence": None,
        "licence_url": None,
        "attribution": None,
        "notes": (
            f"The GDACS terms-of-use page returned HTTP 404 on {REGISTRY_VERIFIED_ON}, so no licence "
            "or attribution text was retrieved. Confirm with GDACS before publishing a credit."
        ),
    },
    "usgs_shakemap": {
        "dataset": "USGS ShakeMap",
        "provider": "U.S. Geological Survey",
        "catalogue_id": None,
        "doi": None,
        "url": "https://earthquake.usgs.gov/data/shakemap/",
        "licence": "U.S. Public Domain (USGS-authored or produced data and information)",
        "licence_url": "https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits",
        "attribution": "Credit: U.S. Geological Survey, Department of the Interior/USGS",
    },
    "acled": {
        "dataset": "ACLED (Armed Conflict Location & Event Data)",
        "provider": "ACLED",
        "catalogue_id": None,
        "doi": None,
        "url": "https://acleddata.com",
        "licence": "ACLED End User Licence Agreement and Content Usage Terms (no open licence)",
        "licence_url": "https://acleddata.com/eula",
        "attribution": (
            "Acknowledge ACLED (Armed Conflict Location & Event Data) clearly. State the access date, "
            "the data filters used (countries, dates, event types), how the data were manipulated, "
            "and anything added or amended (ACLED Attribution Policy)."
        ),
    },
    "cod_ab": {
        "dataset": "OCHA COD-AB administrative boundaries",
        "provider": "OCHA and national mapping authorities via HDX",
        "catalogue_id": None,
        "doi": None,
        "url": "https://data.humdata.org/",
        "licence": "Creative Commons Attribution for Intergovernmental Organisations (CC BY-IGO)",
        "licence_url": "https://creativecommons.org/licenses/by/3.0/igo/",
        "attribution": None,
        "notes": (
            f"Licence read from the HDX cod-ab-afg, -ukr, -mng and -yem datasets on {REGISTRY_VERIFIED_ON}. "
            "HDX sets the licence per country dataset, so confirm it for other countries."
        ),
    },
}

_DATASET_FIELDS = (
    "dataset",
    "provider",
    "catalogue_id",
    "version",
    "doi",
    "url",
    "access_date",
    "period",
    "area",
    "selection",
    "sha256",
    "licence",
    "licence_url",
    "attribution",
)

# Strings that must never reach run metadata.
_ABSOLUTE_PATH = re.compile(r"(^|[\s\"'=(])(/[A-Za-z0-9_.~-]+/|~/|[A-Za-z]:\\)")
_SECRET = re.compile(
    r"(api[_-]?key|secret|token|password|passwd|bearer\s|authorization|\bkey\s*[:=]\s*\S{8,}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:)",
    re.IGNORECASE,
)


def _iter_strings(value: Any) -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield "", value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield str(k), str(k)
            for _, s in _iter_strings(v):
                yield str(k), s
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            yield from _iter_strings(v)


def validate_data_source_entry(entry: dict[str, Any]) -> None:
    """Raise ValueError if an entry carries a local absolute path or anything credential-like."""

    for field, text in _iter_strings(entry):
        if _ABSOLUTE_PATH.search(text):
            raise ValueError(
                f"data_sources entry {entry.get('dataset')!r}: local path in {field!r}: {text!r}"
            )
        if _SECRET.search(text):
            raise ValueError(
                f"data_sources entry {entry.get('dataset')!r}: credential-like text in {field!r}"
            )


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _as_date_str(value: str | date | None) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError as exc:
        raise ValueError(f"access_date must be an ISO date (YYYY-MM-DD), got {value!r}.") from exc


# --- retrieval records -------------------------------------------------------------------------


def retrieval_record_path(path: str | Path) -> Path:
    p = Path(path)
    return p.with_name(p.name + RETRIEVAL_SUFFIX)


def write_retrieval_record(
    path: str | Path,
    *,
    retrieved_date: str | date | None = None,
    source: str | None = None,
) -> Path:
    """Record when ``path`` was retrieved (default: today, UTC). ``source`` is a dataset id or URL,
    never a credential."""

    record = {"retrieved_date": _as_date_str(retrieved_date) or _today_utc()}
    if source:
        record["source"] = source
    out = retrieval_record_path(path)
    validate_data_source_entry(record)
    out.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return out


def read_retrieval_date(path: str | Path) -> str | None:
    """Return the recorded retrieval date for ``path``, or None if there is no valid record."""

    rec = retrieval_record_path(path)
    if not rec.exists():
        return None
    try:
        return _as_date_str(json.loads(rec.read_text(encoding="utf-8")).get("retrieved_date"))
    except (ValueError, OSError):
        return None


def latest_retrieval_date(paths: Iterable[str | Path]) -> tuple[str | None, int, int]:
    """Latest recorded retrieval date over ``paths``.

    Returns ``(date_or_None, n_known, n_unknown)``. When any file has no record the overall date
    is still the latest known one, and the caller should note the gap (``n_unknown > 0``).
    """

    dates = []
    unknown = 0
    for p in paths:
        d = read_retrieval_date(p)
        if d is None:
            unknown += 1
        else:
            dates.append(d)
    return (max(dates) if dates else None), len(dates), unknown


# --- entry construction --------------------------------------------------------------------------


def build_data_source(
    key: str,
    *,
    version: str | None = None,
    access_date: str | date | None = None,
    period: dict[str, str] | None = None,
    area: str | dict[str, Any] | None = None,
    selection: dict[str, Any] | None = None,
    sha256: str | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """One ``data_sources`` entry: registry facts for ``key`` plus this run's facts.

    ``access_date`` is the retrieval date (None when unknown). ``overrides`` replace registry
    values (for example ``catalogue_id`` or ``url`` where the run knows better).
    """

    if key not in REGISTRY:
        raise KeyError(f"Unknown data source '{key}'. Known: {sorted(REGISTRY)}")
    base = dict(REGISTRY[key])
    notes = base.pop("notes", None)
    base.update(overrides)
    acc = _as_date_str(access_date)
    year = acc[:4] if acc else "[Year]"
    attribution = base.get("attribution")
    entry: dict[str, Any] = {name: base.get(name) for name in _DATASET_FIELDS}
    entry["attribution"] = attribution.format(year=year) if isinstance(attribution, str) else attribution
    entry["version"] = version
    entry["access_date"] = acc
    entry["period"] = period
    entry["area"] = area
    entry["selection"] = selection
    entry["sha256"] = sha256
    if notes:
        entry["notes"] = notes
    validate_data_source_entry(entry)
    return entry


def add_data_source(metadata: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    """Append ``entry`` to ``metadata['data_sources']``; warn and log when access_date is unknown."""

    validate_data_source_entry(entry)
    metadata.setdefault("data_sources", []).append(entry)
    if entry.get("access_date") is None:
        msg = (
            f"data_sources: access date unknown for {entry.get('dataset')!r}; recorded as null. "
            "Record it with `wia-hazards record-retrieval` or pass the access-date option."
        )
        warnings.warn(msg, RuntimeWarning, stacklevel=2)
        metadata.setdefault("warnings", []).append({"stage": "data_sources", "message": msg})
    return entry


# --- facts read from the input itself ----------------------------------------------------------------

_WORLDPOP_NAME = re.compile(
    r"^(?P<iso>[a-z]{3})_pop_(?P<year>\d{4})_(?P<kind>CN|UC)_(?P<res>\d+m)_(?P<release>R\d{4}[A-Z])_(?P<ver>v\d+)",
    re.IGNORECASE,
)


def worldpop_facts(worldpop_path: str | Path) -> dict[str, Any]:
    """Version, population year and selection parsed from a WorldPop file name."""

    m = _WORLDPOP_NAME.match(Path(worldpop_path).name)
    if not m:
        return {"version": None, "selection": {"file_name": Path(worldpop_path).name}}
    return {
        "version": f"{m['release']} {m['ver']}",
        "selection": {
            "population_year": int(m["year"]),
            "constrained": m["kind"].upper() == "CN",
            "resolution": m["res"],
            "file_name": Path(worldpop_path).name,
        },
        "area": m["iso"].upper(),
    }


def worldpop_data_source(
    worldpop_path: str | Path,
    *,
    iso3: str,
    sha256: str | None,
    access_date: str | date | None = None,
) -> dict[str, Any]:
    facts = worldpop_facts(worldpop_path)
    return build_data_source(
        "worldpop",
        version=facts["version"],
        access_date=access_date if access_date is not None else read_retrieval_date(worldpop_path),
        area=iso3.upper(),
        selection=facts["selection"],
        sha256=sha256,
    )


_IBTRACS_NAME = re.compile(r"^ibtracs\.(?P<subset>[A-Za-z0-9_-]+)\.list\.(?P<ver>v\d+r\d+)", re.IGNORECASE)


def ibtracs_facts(ibtracs_path: str | Path) -> dict[str, Any]:
    m = _IBTRACS_NAME.match(Path(ibtracs_path).name)
    if not m:
        return {"version": None, "subset": None}
    return {"version": m["ver"], "subset": m["subset"]}


_ACLED_NAME_DATE = re.compile(r"^ACLED Data_(?P<d>\d{4}-\d{2}-\d{2})", re.IGNORECASE)


def acled_access_date_from_name(acled_path: str | Path) -> str | None:
    """ACLED export file names (``ACLED Data_YYYY-MM-DD...``) carry the download date."""

    m = _ACLED_NAME_DATE.match(Path(acled_path).name)
    return m["d"] if m else None


def hydrorivers_data_source(
    hydrorivers_path: str | Path, *, sha256: str | None, access_date: str | date | None = None
) -> dict[str, Any]:
    m = re.search(r"v\d+", Path(hydrorivers_path).name, re.IGNORECASE)
    return build_data_source(
        "hydrorivers",
        version=m.group(0).lower() if m else None,
        access_date=access_date if access_date is not None else read_retrieval_date(hydrorivers_path),
        sha256=sha256,
        selection={"file_name": Path(hydrorivers_path).name},
    )


def admin_data_source(admin_source: dict[str, Any], *, iso3: str) -> dict[str, Any]:
    """COD-AB entry from a run's ``admin_source`` block, without its local path."""

    return build_data_source(
        "cod_ab",
        version=admin_source.get("vintage"),
        access_date=admin_source.get("access_date"),
        area=iso3.upper(),
        selection={
            "admin_level": admin_source.get("admin_level"),
            "authority": admin_source.get("authority"),
        },
        sha256=admin_source.get("sha256"),
    )


# --- helpers shared by the pipelines ---------------------------------------------------------------


def run_period(config: Any) -> dict[str, str]:
    """``period`` for a run's analysis window (a RunConfig)."""

    return {"start": config.window_start.isoformat(), "end": config.window_end.isoformat()}


def add_cds_data_source(
    metadata: dict[str, Any],
    key: str,
    zip_paths: Iterable[str | Path],
    *,
    version: str | None,
    period: dict[str, str] | None,
    area: str | dict[str, Any] | None,
    selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add a CDS/EWDS-backed dataset. ``access_date`` is the latest retrieval date over the monthly
    downloads, and is only stated when every download has a retrieval record; otherwise it is null
    (with a warning) and ``selection`` says how many downloads lacked one."""

    latest, n_known, n_unknown = latest_retrieval_date(zip_paths)
    sel = dict(selection or {})
    sel["downloads"] = n_known + n_unknown
    if n_unknown:
        sel["downloads_without_retrieval_record"] = n_unknown
    entry = build_data_source(
        key,
        version=version,
        access_date=latest if n_unknown == 0 else None,
        period=period,
        area=area,
        selection=sel,
    )
    return add_data_source(metadata, entry)


def add_population_and_admin_sources(
    metadata: dict[str, Any],
    *,
    iso3: str,
    worldpop_path: str | Path,
    worldpop_sha256: str | None,
    worldpop_access_date: str | date | None = None,
) -> None:
    """Add the population raster and (when the run recorded one) the COD-AB boundary entries."""

    add_data_source(
        metadata,
        worldpop_data_source(
            worldpop_path, iso3=iso3, sha256=worldpop_sha256, access_date=worldpop_access_date
        ),
    )
    if metadata.get("admin_source"):
        add_data_source(metadata, admin_data_source(metadata["admin_source"], iso3=iso3))
