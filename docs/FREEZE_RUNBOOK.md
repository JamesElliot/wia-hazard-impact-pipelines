# Freeze Runbook (Headless Batch)

This runbook is the operational checklist for freezing the repo and running the batch process on a headless machine.

## 1) Freeze On Source Machine

From the repository root:

```bash
git add .
git commit -m "freeze: baseline hazard pipelines before headless batch run"
git tag -a freeze-pre-headless-run-2026-02-26 -m "Pre-headless batch freeze"
```

## 2) Copy Repo To Headless Machine

Use a full directory copy so `.git` metadata is preserved.

```bash
rsync -av --progress <SOURCE_REPO_PATH>/wia-hazard-layers/ <HEADLESS_PATH>/wia-hazard-layers/
```

## 3) Headless Machine Setup

From `<HEADLESS_PATH>/wia-hazard-layers`:

```bash
conda env create -f environment.yaml
conda activate wia-hazard-pipelines
python -m pip install -e . --no-build-isolation
```

Required runtime credentials:
- CDS API credentials configured for `cdsapi`.

## 4) Verify Inputs

Confirm these exist before running:
- COD-AB file: `data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip`
- WorldPop rasters: `data/population/*.tif`
- ACLED bulk/country files: `data/violence/*`
- Batch manifest: `data/batch_tasks.csv`

## 5) Preflight (Repeatable)

```bash
conda run -n wia-hazard-pipelines env PYTHONPATH=src python scripts/batch_preflight.py \
  --manifest ./data/batch_tasks.csv \
  --admin-path ./data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip \
  --worldpop-dir ./data/population \
  --acled-dir ./data/violence \
  --iso-lookup-path ./data/violence/iso_country-codes.csv \
  --acled-bulk-path ./data/violence/acled_all_20250101-20251231.csv \
  --acled-bulk-iso-column iso \
  --sample-year 2025 \
  --sample-month 1 \
  --flood-mode extents \
  --out-dir ./outputs/batch/preflight_v2
```

Primary artifacts:
- `outputs/batch/preflight_v2/batch_readiness_report.csv`
- `outputs/batch/preflight_v2/batch_preflight_report.csv`
- `outputs/batch/preflight_v2/batch_issues.md`

## 6) Batch Dry-Run

```bash
conda run -n wia-hazard-pipelines env PYTHONPATH=src python -m wia_pipelines.cli batch-run \
  --readiness-report ./outputs/batch/preflight_v2/batch_readiness_report.csv \
  --preflight-report ./outputs/batch/preflight_v2/batch_preflight_report.csv \
  --out-dir ./outputs/batch/run \
  --pipeline spei --pipeline utci --pipeline flood --pipeline violence \
  --resume \
  --dry-run
```

Expect `n_failed: 0`.

## 7) Start Real Batch Run

```bash
conda run -n wia-hazard-pipelines env PYTHONPATH=src python -m wia_pipelines.cli batch-run \
  --readiness-report ./outputs/batch/preflight_v2/batch_readiness_report.csv \
  --preflight-report ./outputs/batch/preflight_v2/batch_preflight_report.csv \
  --out-dir ./outputs/batch/run \
  --pipeline spei --pipeline utci --pipeline flood --pipeline violence \
  --resume
```

## 8) Monitor Progress

Monitor:
- `outputs/batch/run/batch_run_status.json`
- `outputs/batch/run/batch_run_report.csv`
- `outputs/batch/run/logs/`

Quick status check:

```bash
tail -n +1 outputs/batch/run/batch_run_status.json
```

## 9) Failure Handling / Resume

- Do not delete run artifacts.
- Fix root cause.
- Re-run the exact same `batch-run` command with `--resume`.
- Completed steps (`SUCCESS`/`SKIP`) will not be rerun.

## 10) Finalize

When batch completes:
1. Archive `outputs/batch/run/` and `outputs/batch/preflight_v2/`.
2. Commit final code/doc updates.
3. Tag release candidate:

```bash
git add .
git commit -m "batch: headless run complete"
git tag -a freeze-post-headless-run-YYYY-MM-DD -m "Post headless batch run"
```

