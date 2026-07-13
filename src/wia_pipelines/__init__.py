"""Reusable helpers for WIA hazard pipelines.

Imports are lazy to keep package import lightweight in environments that do not
have the full geospatial stack installed.
"""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "LayerSpec",
    "audit_hazard_layer_coverage",
    "prepare_geography",
    "plot_geography_overview",
    "RunConfig",
    "build_run_paths",
    "initialize_run_metadata",
    "validate_run_metadata",
]


def __getattr__(name: str):
    if name in {"LayerSpec", "audit_hazard_layer_coverage"}:
        module = import_module("wia_pipelines.coverage_audit")
        return getattr(module, name)
    if name in {"prepare_geography", "plot_geography_overview"}:
        module = import_module("wia_pipelines.geography")
        return getattr(module, name)
    if name in {
        "RunConfig",
        "build_run_paths",
        "initialize_run_metadata",
        "validate_run_metadata",
    }:
        module = import_module("wia_pipelines.config")
        return getattr(module, name)
    raise AttributeError(f"module 'wia_pipelines' has no attribute '{name}'")
