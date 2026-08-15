from __future__ import annotations

import calendar
from typing import Any


def days_for_year_month(year: int, month: int) -> list[str]:
    last_day = calendar.monthrange(year, month)[1]
    return [f"{d:02d}" for d in range(1, last_day + 1)]


def spei_sample_request(
    year: int,
    month: int,
    area_nwse: list[float],
) -> dict[str, Any]:
    return {
        "variable": ["standardised_precipitation_evapotranspiration_index"],
        "accumulation_period": ["12"],
        "version": "1_0",
        "product_type": ["reanalysis"],
        "dataset_type": "consolidated_dataset",
        "year": [str(year)],
        "month": [f"{month:02d}"],
        "area": area_nwse,
    }


def glofas_sample_request(
    year: int,
    month: int,
    day: int,
    area_nwse: list[float],
    system_version: str = "version_4_0",
    hydrological_model: str = "lisflood",
) -> dict[str, Any]:
    """Single-day `cems-glofas-historical` request for preflight coverage sampling.

    GloFAS is daily, not monthly like SPEI/UTCI, so this samples one day
    rather than one month. Field names/values have been confirmed against the
    live EWDS `cems-glofas-historical` process catalogue and a real download
    was executed end-to-end -- see docs/hydrodrought-implementation-plan.md
    §7 ("Catalogue verification (done)"). This is the single place to update
    them if the catalogue schema changes in future.
    """

    return {
        "system_version": [system_version],
        "hydrological_model": [hydrological_model],
        "product_type": ["consolidated"],
        "timespan": ["time_mean"],
        "variable": ["average_river_discharge_in_the_last_24_hours"],
        "year": [str(year)],
        "month": [f"{month:02d}"],
        "day": [f"{day:02d}"],
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": area_nwse,
    }


def utci_sample_request(
    year: int,
    month: int,
    area_nwse: list[float],
) -> dict[str, Any]:
    return {
        "variable": ["universal_thermal_climate_index_daily_statistics"],
        "version": "1_1",
        "product_type": "consolidated_dataset",
        "year": [str(year)],
        "month": [f"{month:02d}"],
        "day": days_for_year_month(year, month),
        "area": area_nwse,
    }
