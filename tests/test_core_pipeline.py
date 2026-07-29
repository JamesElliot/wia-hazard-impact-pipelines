from __future__ import annotations

import json

import pandas as pd

import pytest

from wia_pipelines.config import RunConfig
from wia_pipelines.core.pipeline import (
    HAZARD_METHODS,
    RunAlreadyCompleteError,
    build_hazard_run_context,
    record_artifact,
    run_already_complete,
    standardize_admin_summary,
    sync_run_metadata,
)
from wia_pipelines.hazards.hydrodrought import PERSISTENCE_MONTHS


def test_method_registry_covers_every_supported_hazard():
    assert set(HAZARD_METHODS) == {
        "cyclone",
        "drought",
        "earthquake",
        "flood",
        "heat",
        "hydrodrought",
        "violence",
    }
    assert all(method.method_version for method in HAZARD_METHODS.values())
    assert all(method.population_rule for method in HAZARD_METHODS.values())


def test_hydrodrought_population_rule_matches_implemented_persistence():
    # Regression test for a past defect: the registry text once said "30
    # consecutive days", but the implemented (and documented) rule is
    # PERSISTENCE_MONTHS consecutive months. This pins the text to the real
    # constant so the two can't silently drift apart again.
    rule = HAZARD_METHODS["hydrodrought"].population_rule
    assert f"{PERSISTENCE_MONTHS} consecutive months" in rule
    assert "consecutive days" not in rule


def test_run_context_uses_canonical_hazard_path_and_metadata(tmp_path):
    config = RunConfig(
        hazard="drought",
        iso3="MLI",
        as_of_date="2025-12-31",
        output_root=tmp_path,
    )
    context = build_hazard_run_context(config)

    assert context["layout"]["base"].name == "drought"
    assert context["layout"]["base"].parent.parent.name == "MLI"
    assert context["metadata"]["pipeline"] == "water_scarcity_spei3"
    assert context["metadata"]["method_version"] == "0.1.0"

    artifact = context["layout"]["logs"] / "audit.txt"
    artifact.write_text("ok", encoding="utf-8")
    record_artifact(context["metadata"], "audit", artifact, "test artifact")
    sync_run_metadata(context["metadata"], context["metadata_path"])
    saved = json.loads(context["metadata_path"].read_text(encoding="utf-8"))
    assert saved["artifacts"][0]["kind"] == "audit"


def test_run_already_complete_is_none_without_a_status_marker(tmp_path):
    # PROD-001: build_hazard_run_context(write_metadata=True) itself writes
    # run_metadata.json at the very *start* of every real hazard run, before
    # any actual computation -- so its mere existence/schema-validity must
    # NOT be read as "this run finished successfully".
    config = RunConfig(hazard="drought", iso3="MLI", as_of_date="2025-12-31", output_root=tmp_path)
    context = build_hazard_run_context(config)
    assert "status" not in context["metadata"]
    assert run_already_complete(context["layout"]) is None


def test_run_already_complete_is_the_metadata_once_status_success_is_written(tmp_path):
    config = RunConfig(hazard="drought", iso3="MLI", as_of_date="2025-12-31", output_root=tmp_path)
    context = build_hazard_run_context(config)
    context["metadata"]["status"] = "SUCCESS"
    sync_run_metadata(context["metadata"], context["metadata_path"])

    found = run_already_complete(context["layout"])
    assert found is not None
    assert found["status"] == "SUCCESS"


def test_skip_if_complete_defaults_to_false_and_always_recomputes(tmp_path):
    # Opt-in only: the guard must never fire unless a caller explicitly asks
    # for it, so every existing caller's behavior is unchanged by default.
    config = RunConfig(hazard="drought", iso3="MLI", as_of_date="2025-12-31", output_root=tmp_path)
    context = build_hazard_run_context(config)
    context["metadata"]["status"] = "SUCCESS"
    sync_run_metadata(context["metadata"], context["metadata_path"])

    # No skip_if_complete kwarg at all -- same as every caller before this feature existed.
    second = build_hazard_run_context(config)
    assert "status" not in second["metadata"]


def test_skip_if_complete_raises_when_a_valid_success_run_exists(tmp_path):
    config = RunConfig(hazard="drought", iso3="MLI", as_of_date="2025-12-31", output_root=tmp_path)
    context = build_hazard_run_context(config, skip_if_complete=True)
    context["metadata"]["status"] = "SUCCESS"
    sync_run_metadata(context["metadata"], context["metadata_path"])

    with pytest.raises(RunAlreadyCompleteError) as excinfo:
        build_hazard_run_context(config, skip_if_complete=True)
    assert excinfo.value.metadata["status"] == "SUCCESS"
    assert excinfo.value.layout["base"] == context["layout"]["base"]


def test_skip_if_complete_does_not_raise_for_a_partial_prior_run(tmp_path):
    # A run that started (run_metadata.json exists, schema-valid) but never
    # reached its terminal status="SUCCESS" write -- e.g. a crash mid-run --
    # must still be treated as incomplete and re-run, even with
    # skip_if_complete=True.
    config = RunConfig(hazard="drought", iso3="MLI", as_of_date="2025-12-31", output_root=tmp_path)
    build_hazard_run_context(config)  # metadata written, but no "status" key

    second = build_hazard_run_context(config, skip_if_complete=True)
    assert "status" not in second["metadata"]


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
