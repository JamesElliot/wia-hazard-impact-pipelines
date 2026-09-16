#!/usr/bin/env bash
set -euo pipefail

# Runs the hazard set (flood, heat, drought/SPEI, hydrological drought
# GloFAS-SRI, earthquake, cyclone) for PSE (State of Palestine) at admin3,
# for one batch window. Violence (ACLED) is run separately once a
# window-spanning ACLED export is available (see --acled-csv on
# run-violence). admin3 == admin2 for PSE in the COD-AB archive (no
# sub-governorate boundaries exist), so this just labels the run at the
# finer level; results are identical to an admin2 run.
#
# Usage:
#   scripts/run_pse_admin3_batch.sh <AS_OF_DATE> <LOOKBACK_MONTHS> [BATCH_LABEL]

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <AS_OF_DATE YYYY-MM-DD> <LOOKBACK_MONTHS> [BATCH_LABEL]" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

CONDA_ENV="${CONDA_ENV:-wia-hazard-pipelines}"
AS_OF_DATE="$1"
LOOKBACK_MONTHS="$2"
BATCH_LABEL="${3:-$AS_OF_DATE}"
TARGET_ADM_LEVEL="3"
ADMIN_LAYER="admin3"
ADMIN_PATH="${ADMIN_PATH:-./data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip}"
IBTRACS_PATH="${IBTRACS_PATH:-./data/cyclone/ibtracs.last3years.list.v04r01.csv}"
ADMIN3_FIELDS_CONFIG="${ADMIN3_FIELDS_CONFIG:-./configs/pse_admin3_fields.yml}"
WORLDPOP_PATH="${WORLDPOP_PATH:-./data/population/pse_pop_2025_CN_100m_R2025A_v1.tif}"
ISO3="PSE"

echo "=== Batch ${BATCH_LABEL}: as_of_date=${AS_OF_DATE} lookback_months=${LOOKBACK_MONTHS} admin3 (PSE) ==="

echo "[0/1] Checking shared inputs"
test -f "$ADMIN_PATH"
test -f "$IBTRACS_PATH"
test -f "$WORLDPOP_PATH"

echo "--- ${ISO3}: flood ---"
conda run -n "$CONDA_ENV" env PYTHONPATH=src python scripts/run_flood_pipeline.py \
  --iso3 "$ISO3" \
  --as-of-date "$AS_OF_DATE" \
  --lookback-months "$LOOKBACK_MONTHS" \
  --target-adm-level "$TARGET_ADM_LEVEL" \
  --admin-path "$ADMIN_PATH" \
  --admin-layer "$ADMIN_LAYER" \
  --worldpop-path "$WORLDPOP_PATH"

echo "--- ${ISO3}: heat (UTCI) ---"
conda run -n "$CONDA_ENV" env PYTHONPATH=src python scripts/run_utci_pipeline.py \
  --iso3 "$ISO3" \
  --as-of-date "$AS_OF_DATE" \
  --lookback-months "$LOOKBACK_MONTHS" \
  --target-adm-level "$TARGET_ADM_LEVEL" \
  --admin-path "$ADMIN_PATH" \
  --admin-layer "$ADMIN_LAYER" \
  --worldpop-path "$WORLDPOP_PATH"

echo "--- ${ISO3}: drought (SPEI) ---"
conda run -n "$CONDA_ENV" env PYTHONPATH=src python scripts/run_spei_pipeline.py \
  --iso3 "$ISO3" \
  --as-of-date "$AS_OF_DATE" \
  --lookback-months "$LOOKBACK_MONTHS" \
  --target-adm-level "$TARGET_ADM_LEVEL" \
  --admin-path "$ADMIN_PATH" \
  --admin-layer "$ADMIN_LAYER" \
  --worldpop-path "$WORLDPOP_PATH"

echo "--- ${ISO3}: hydrological drought (GloFAS-SRI) ---"
conda run -n "$CONDA_ENV" env PYTHONPATH=src python -m wia_pipelines.cli run-hydrodrought \
  --iso3 "$ISO3" \
  --as-of-date "$AS_OF_DATE" \
  --lookback-months "$LOOKBACK_MONTHS" \
  --target-adm-level "$TARGET_ADM_LEVEL" \
  --admin-path "$ADMIN_PATH" \
  --admin-layer "$ADMIN_LAYER" \
  --worldpop-path "$WORLDPOP_PATH"

echo "--- ${ISO3}: earthquake ---"
conda run -n "$CONDA_ENV" env PYTHONPATH=src python -m wia_pipelines.cli run-earthquake \
  --iso3 "$ISO3" \
  --as-of-date "$AS_OF_DATE" \
  --lookback-months "$LOOKBACK_MONTHS" \
  --target-adm-level "$TARGET_ADM_LEVEL" \
  --admin-path "$ADMIN_PATH" \
  --admin-layer "$ADMIN_LAYER" \
  --worldpop-path "$WORLDPOP_PATH" \
  --config "$ADMIN3_FIELDS_CONFIG"

echo "--- ${ISO3}: cyclone ---"
conda run -n "$CONDA_ENV" env PYTHONPATH=src python -m wia_pipelines.cli run-cyclone \
  --iso3 "$ISO3" \
  --as-of-date "$AS_OF_DATE" \
  --lookback-months "$LOOKBACK_MONTHS" \
  --target-adm-level "$TARGET_ADM_LEVEL" \
  --admin-path "$ADMIN_PATH" \
  --admin-layer "$ADMIN_LAYER" \
  --worldpop-path "$WORLDPOP_PATH" \
  --ibtracs-path "$IBTRACS_PATH" \
  --config "$ADMIN3_FIELDS_CONFIG" \
  --gdacs-auto

echo "Done: PSE admin3 batch ${BATCH_LABEL} (flood, heat, drought, hydrodrought, earthquake, cyclone)."
