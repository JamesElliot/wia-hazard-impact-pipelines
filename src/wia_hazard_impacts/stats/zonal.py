"""Admin2 zonal statistics helpers.

This module will hold the shared, tested implementation used by all hazard
pipelines. Initially, keep it minimal and add as we refactor notebooks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ZonalResultSchema:
    """Canonical output columns for admin2 results.

    We will enforce these across all hazards to simplify import into WIA models.
    """

    admin_key: str = "adm2_pcode"
    col_pop_total: str = "pop_total"
    col_pop_affected: str = "pop_affected"
    col_pct_affected: str = "pct_affected"
