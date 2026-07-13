# Repo Consolidation TODO

## Current State (Completed)

- [x] Shared core modules extracted (`io_paths`, `admin`, `worldpop`, `cds`, `raster_ops`, `aggregation`).
- [x] Standard run metadata contract and schema validation in place.
- [x] Standardized post-run checks + parity reports:
  - [x] `spei-postrun`
  - [x] `utci-postrun`
  - [x] `flood-postrun`
  - [x] `violence-postrun`
- [x] Progress/status snapshots added to heavy steps in all four notebooks.
- [x] Coverage preflight workflow implemented (including CDS and flood extent checks).

## Pipeline Plan (Next Steps)

### SPEI (Drought)
- [ ] Remove remaining notebook-local utility duplication in later cells.
- [x] Extract module runner (`run_spei_pipeline`) into `src/wia_pipelines/hazards/spei.py` for script/batch execution.
- [x] Add `wia-hazards run-spei ...` CLI runner for notebook-equivalent headless execution.
- [x] Add script entrypoint `scripts/run_spei_pipeline.py` (module-based runner).
- [ ] Add one golden regression case and lock expected key outputs.
- [ ] Add SPEI intensity surface + derived binary mask pattern (aligned with flood/violence severity approach).

### UTCI (Heat)
- [ ] Move remaining shared notebook logic to core/hazard modules.
- [ ] Add explicit caching/reuse strategy for monthly consolidated vs intermediate downloads.
- [x] Add `wia-hazards run-utci ...` CLI runner.
- [x] Add script entrypoint `scripts/run_utci_pipeline.py` (module-based runner).
- [x] Replace transition notebook-backed runner with pure module `run_utci_pipeline`.
- [ ] Add one golden regression case and lock expected key outputs.
- [ ] Add UTCI intensity surface + derived binary mask pattern (aligned with flood/violence severity approach).

### Flood (GFM)
- [ ] Finalize STAC preflight modes in notebook + docs (`extents` no-download, `asset` sample read).
- [ ] Add stronger remote-read retry/backoff handling for unstable tiles.
- [ ] Add performance guardrails for large countries (tiling/chunk limits + runtime logging summary).
- [x] Add `wia-hazards run-flood ...` CLI runner for module-based end-to-end execution.
- [x] Add script entrypoint `scripts/run_flood_pipeline.py` (module-based runner).
- [x] Replace transition notebook-backed runner with pure module `run_flood_pipeline`.
- [ ] Add one golden regression case and lock expected key outputs.

### Violence (ACLED)
- [x] Add preflight checks and standardized post-run parity.
- [x] Add event-count raster and derived binary mask flow.
- [x] Add optional included-event-type filter (legacy default excludes protests).
- [x] Extend parity checks to validate new event-count/pop-weighted outputs explicitly.
- [x] Add `wia-hazards run-violence ...` CLI runner.
- [x] Add one golden regression case and lock expected key outputs.

## Cross-Cutting Platform Tasks

- [x] Add shared multi-country batch manifest normalization + readiness + preflight tooling (`batch-preflight`).
- [x] Add shared multi-country batch execution runner (`batch-run`) with retries, resume, heartbeat status JSON, and per-step logs.
- [ ] Ensure all pipelines emit identical output contract fields in `run_metadata.json`.
- [ ] Add CI workflow for tests + smoke runs.
- [ ] Add docs for common failure modes (CDS auth, STAC/network, CRS/alignment, import paths).
- [ ] Finalize data management guidance (what stays in repo vs external storage).

## Documentation Plan

- [ ] Add `docs/pipelines.md` with per-pipeline flow and output contract tables.
- [ ] Add `docs/preflight-checks.md` with thresholds and interpretation guidance.
- [ ] Add flood preflight usage examples for `--flood-mode extents` and `--flood-mode asset`.
