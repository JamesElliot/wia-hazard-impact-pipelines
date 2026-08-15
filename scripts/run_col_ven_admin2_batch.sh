#!/usr/bin/env bash
set -euo pipefail

# Runs the full hazard set (flood, heat, drought/SPEI, hydrological drought
# GloFAS-SRI, earthquake, cyclone, violence/ACLED) for COL and VEN at admin2
# (the COD-AB default level for both countries), for one batch window.
# Violence uses a single combined ACLED export covering both countries
# (see --acled-csv); the pipeline spatially intersects events against each
# country's admin polygons, so no per-country ACLED file is needed.
#
# Usage:
#   scripts/run_col_ven_admin2_batch.sh <AS_OF_DATE> <LOOKBACK_MONTHS> [BATCH_LABEL]

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
TARGET_ADM_LEVEL="2"
ADMIN_LAYER="admin2"
ADMIN_PATH="${ADMIN_PATH:-./data/cod-ab/global_admin_boundaries_matched_latest.gdb.zip}"
IBTRACS_PATH="${IBTRACS_PATH:-./data/cyclone/ibtracs.last3years.list.v04r01.csv}"
ACLED_CSV="${ACLED_CSV:-./data/violence/ACLED_COL-VEN_2026-08-15_event_date_from_2025-01-01_event_date_to_2026-08-15.csv}"

ISO3_LIST=(COL VEN)

echo "=== Batch ${BATCH_LABEL}: as_of_date=${AS_OF_DATE} lookback_months=${LOOKBACK_MONTHS} admin2 (COL/VEN) ==="

echo "[0/1] Checking shared inputs"
test -f "$ADMIN_PATH"
test -f "$IBTRACS_PATH"
test -f "$ACLED_CSV"

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
    --worldpop-path "$WORLDPOP_PATH"

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
    --gdacs-auto

  echo "--- ${ISO3}: violence (ACLED) ---"
  conda run -n "$CONDA_ENV" env PYTHONPATH=src python -m wia_pipelines.cli run-violence \
    --iso3 "$ISO3" \
    --as-of-date "$AS_OF_DATE" \
    --lookback-months "$LOOKBACK_MONTHS" \
    --target-adm-level "$TARGET_ADM_LEVEL" \
    --admin-path "$ADMIN_PATH" \
    --admin-layer "$ADMIN_LAYER" \
    --worldpop-path "$WORLDPOP_PATH" \
    --acled-csv "$ACLED_CSV"
done

echo "Done: COL/VEN admin2 batch ${BATCH_LABEL} (flood, heat, drought, hydrodrought, earthquake, cyclone, violence)."
