from __future__ import annotations

import json

import pandas as pd

from wia_pipelines.config import RunConfig
from wia_pipelines.core.pipeline import (
    HAZARD_METHODS,
    build_hazard_run_context,
    record_artifact,
    standardize_admin_summary,
    sync_run_metadata,
)


def test_method_registry_covers_every_supported_hazard():
    assert set(HAZARD_METHODS) == {"cyclone", "drought", "flood", "heat", "violence"}
    assert all(method.method_version for method in HAZARD_METHODS.values())
    assert all(method.population_rule for method in HAZARD_METHODS.values())


def test_run_context_uses_canonical_hazard_path_and_metadata(tmp_path):
    config = RunConfig(
        hazard="drought",
        iso3="MLI",
        as_of_date="2025-12-31",
        output_root=tmp_path,
    )
    context = build_hazard_run_context(config)

    assert context["layout"]["base"].parent.parent.name == "drought"
    assert context["metadata"]["pipeline"] == "water_scarcity_spei3"
    assert context["metadata"]["method_version"] == "0.1.0"

    artifact = context["layout"]["logs"] / "audit.txt"
    artifact.write_text("ok", encoding="utf-8")
    record_artifact(context["metadata"], "audit", artifact, "test artifact")
    sync_run_metadata(context["metadata"], context["metadata_path"])
    saved = json.loads(context["metadata_path"].read_text(encoding="utf-8"))
    assert saved["artifacts"][0]["kind"] == "audit"


def test_standardize_admin_summary_preserves_compatibility_columns():
    config = RunConfig(hazard="flood", iso3="MLI", as_of_date="2025-12-31")
    original = pd.DataFrame(
        {
            "adm2_pcode": ["MLI001"],
            "pop_total": [100.0],
            "pop_affected_flood": [25.0],
            "pct_affected_flood": [25.0],
            "flood_days_max": [3],
        }
    )
    result = standardize_admin_summary(
        original,
        config=config,
        admin_level=2,
        admin_pcode_column="adm2_pcode",
        population_total_column="pop_total",
        population_affected_column="pop_affected_flood",
        pct_affected_column="pct_affected_flood",
    )

    assert result.loc[0, "admin_pcode"] == "MLI001"
    assert result.loc[0, "population_affected"] == 25.0
    assert result.loc[0, "pct_affected"] == 25.0
    assert result.loc[0, "hazard"] == "flood"
    assert result.loc[0, "flood_days_max"] == 3
