# Hazard Pipeline Standard (SPEI, UTCI, Flood)

This project now applies a shared execution pattern across CDS-based and flood notebooks:
- `spei-pipeline.ipynb`
- `utci-pipeline.ipynb`
- `flood-pipeline.ipynb`

## Shared Run Pattern

1. Initialize schema-compliant run metadata at run start.
2. Build AOI from COD admin boundaries and derive buffered CDS area.
3. Run preflight coverage checks (numeric + visual) before heavy downloads.
4. Download/process hazard data.
5. Produce rasters, tables, QC outputs.
6. Run post-run validation (`*-postrun`) and generate parity report.

## Canonical Run Directory Contract

Both pipelines now expose these canonical directories inside each run:
- `base`
- `raw`
- `intermediate`
- `rasters`
- `tables`
- `qc`
- `logs`

### SPEI Compatibility Aliases

For backward compatibility with existing cells:
- `raw_cds -> raw/cds`
- `raw_extracted -> intermediate/cds_extracted`
- `masks_native -> rasters/masks_native`
- `masks_worldpop -> rasters/masks_worldpop`
- `pop_affected -> rasters/pop_affected`

### UTCI Compatibility Aliases

For backward compatibility with existing cells:
- `baseline_raw -> raw/baseline`
- `recent_raw -> raw/recent`
- `baseline_ref -> intermediate/baseline_ref`
- `masks_native -> rasters/masks_native`
- `masks_worldpop -> rasters/masks_worldpop`
- `pop_exposed -> rasters/pop_exposed`

## Preflight Checks

Both pipelines run:
- WorldPop coverage vs admin bounds
- Single-month CDS sample coverage vs admin bounds
- Overlay + grid figures for visual QA

If sample coverage is not full, notebooks fail fast before heavy CDS pulls.

Flood preflight uses:
- WorldPop coverage threshold (default >=98%)
- GFM STAC union bbox coverage threshold (default >=99.999%)

## Post-Run Validation

- SPEI: `wia-hazards spei-postrun --run-dir <run_dir>`
- UTCI: `wia-hazards utci-postrun --run-dir <run_dir>`
- Flood: `wia-hazards flood-postrun --run-dir <run_dir>`

Each command performs metadata validation (warning by default, strict with `--strict-metadata-validation`) and writes parity reports under `qc/`.

## Flood-Specific Outputs

Flood now uses a severity-first pattern:
- `flood_days.tif` (count of flooded days in window)
- `flood_any.tif` (derived binary mask from `flood_days > threshold`)
- `pop_affected_flood_any.tif` (derived from binary mask)
- optional `pop_weighted_flood_days.tif` for severity-weighted exposure

Flood heavy steps include progress/status JSON snapshots in `logs/`:
- `*_cell7_status.json` for streaming flood-day accumulation
