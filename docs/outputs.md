# Outputs contract

The intention is that **all hazards** write the same set of artefacts so WIA country models can ingest results consistently.

## Files

Each run should produce, at minimum:

- `results/<ISO3>_<hazard>_<start>_<end>_admin2.csv`
- `results/<ISO3>_<hazard>_<start>_<end>_mask.tif` (binary/continuous hazard mask on the WorldPop grid)
- `results/<ISO3>_<hazard>_<start>_<end>_pop_affected.tif` (WorldPop * mask)
- `run_metadata.json`

## Admin2 CSV schema (minimum)

| column | meaning |
|---|---|
| `adm2_pcode` | admin2 identifier used in WIA |
| `pop_total` | total population within admin2 (WorldPop sum, aligned to run grid) |
| `pop_affected` | population affected by hazard definition |
| `pct_affected` | `pop_affected / pop_total * 100` |

Hazard-specific extra columns are allowed, but these minimum fields must always exist.
