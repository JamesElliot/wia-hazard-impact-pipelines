# Contributing

## Workflow

1. Keep hazard-specific logic isolated from shared modules in `src/wia_pipelines/hazards`.
2. Put reusable logic in `src/wia_pipelines/core`.
3. Keep notebooks as thin wrappers over package modules where possible.
4. Add/maintain preflight coverage checks before heavy downloads.

## Development Setup

```bash
python -m pip install -e '.[dev]' --no-build-isolation
pytest -q
ruff check src scripts tests
ruff format --check src scripts tests
```

## Standards

- Use ISO3 country codes (uppercase, 3 letters).
- Use ISO dates (`YYYY-MM-DD`).
- Validate run metadata against `schemas/run_metadata.schema.json`.
- Keep outputs under `./outputs/<hazard>/<ISO3>/<run_id>/...`.
- Use canonical run directories in pipelines: `raw`, `intermediate`, `rasters`, `tables`, `qc`, `logs`.
- For coverage checks, include both numeric coverage metrics and visual overlays.
- For long-running download/raster steps, write progress status JSON into the run `logs/` directory.
- Never commit downloaded data, credentials, run outputs, or raw ACLED records.
- Keep the default test suite independent of networks, credentials, and external datasets; mark those checks as `integration`.

## Notebook Notes

- If notebook imports fail (`ModuleNotFoundError: wia_pipelines`), ensure editable install is active in that kernel environment or add `src/` to `sys.path`.
- Keep preflight coverage cells ahead of heavy data downloads and long-running processing cells.
- If backward-compatible alias dirs are used in notebooks, map them to canonical directories rather than creating separate output trees.
- Use post-run validation commands for completed runs:
  - `wia-hazards spei-postrun --run-dir <run_dir>`
  - `wia-hazards utci-postrun --run-dir <run_dir>`
  - `wia-hazards flood-postrun --run-dir <run_dir>`
  - `wia-hazards violence-postrun --run-dir <run_dir>`

## Pull Request Checklist

- Indicator semantics and defaults are documented when changed.
- New outputs follow `docs/output-contract.md` or clearly document a compatibility exception.
- Unit tests, Ruff checks, notebook validation, and the large-file check pass.
- No machine-specific absolute paths, credentials, source datasets, or generated outputs are included.
