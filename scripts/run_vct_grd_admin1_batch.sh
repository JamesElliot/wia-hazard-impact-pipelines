#!/usr/bin/env bash
set -euo pipefail

# Runs the full hazard set (flood, heat, drought, earthquake, cyclone) for
# VCT and GRD at admin1, for one batch window. Violence is skipped: no
# ACLED-derived methodology is being run for this admin1 setup.
#
# Usage:
#   scripts/run_vct_grd_admin1_batch.sh <AS_OF_DATE> <LOOKBACK_MONTHS> [BATCH_LABEL]
#
# Batches for the 2024-01-01..2026-06-30 window:
#   scripts/run_vct_grd_admin1_batch.sh 2024-12-31 12 2024
#   scripts/run_vct_grd_admin1_batch.sh 2025-12-31 12 2025
#   scripts/run_vct_grd_admin1_batch.sh 2026-06-30 6  2026H1

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
TARGET_ADM_LEVEL="1"
ADMIN_LAYER="admin1"
ADMIN_PATH="${ADMIN_PATH:-./data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip}"
IBTRACS_PATH="${IBTRACS_PATH:-./data/cyclone/ibtracs.last3years.list.v04r01.csv}"
ADMIN1_FIELDS_CONFIG="${ADMIN1_FIELDS_CONFIG:-./configs/vct_grd_admin1_fields.yml}"

ISO3_LIST=(VCT GRD)

echo "=== Batch ${BATCH_LABEL}: as_of_date=${AS_OF_DATE} lookback_months=${LOOKBACK_MONTHS} admin1 ==="

echo "[0/1] Checking shared inputs"
test -f "$ADMIN_PATH"
test -f "$IBTRACS_PATH"

for ISO3 in "${ISO3_LIST[@]}"; do
  LOWER_ISO3="$(echo "$ISO3" | tr '[:upper:]' '[:lower:]')"
  WORLDPOP_PATH="./data/population/${LOWER_ISO3}_pop_2025_CN_100m_R2025A_v1.tif"
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

  echo "--- ${ISO3}: earthquake ---"
  conda run -n "$CONDA_ENV" env PYTHONPATH=src python -m wia_pipelines.cli run-earthquake \
    --iso3 "$ISO3" \
    --as-of-date "$AS_OF_DATE" \
    --lookback-months "$LOOKBACK_MONTHS" \
    --target-adm-level "$TARGET_ADM_LEVEL" \
    --admin-path "$ADMIN_PATH" \
    --admin-layer "$ADMIN_LAYER" \
    --worldpop-path "$WORLDPOP_PATH" \
    --config "$ADMIN1_FIELDS_CONFIG"

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
    --config "$ADMIN1_FIELDS_CONFIG" \
    --gdacs-auto
done

echo "Done: VCT/GRD admin1 batch ${BATCH_LABEL} (flood, heat, drought, earthquake, cyclone)."
