# Earthquake indicator (HI-EQ)

## Definition

The reference implementation measures the percentage of an administrative
area's population exposed to potentially damaging earthquake shaking during
the inclusive rolling reference window. It discovers actual earthquakes from
the USGS catalogue, retrieves the latest released ShakeMap for each event, and
resamples continuous Modified Mercalli Intensity (MMI) to the WorldPop grid.

A population cell is affected when its maximum MMI across all qualifying
events is at least VI. The annual maximum counts a residential population cell
once even when several earthquakes affect it. MMI V and VII outputs are
retained as sensitivity scenarios.

## Event and product selection

- The catalogue query has no analytical magnitude cutoff.
- Events without a ShakeMap reference are recorded and excluded before detail
  retrieval.
- Scenarios, exercises, tests, deleted products, products outside the country,
  and products without MMI VI inside the country are excluded with an explicit
  reason.
- The selected product maximizes USGS preferred weight and update time.
- Version, status, source URL, retrieval time, and SHA-256 checksum are retained.
- Version 0.1 reads authoritative `grid.xml`; visualization contours are not used.

## Aggregation and deprivation

Continuous MMI is bilinearly resampled before applying thresholds. Population
counts and all shaking masks use the WorldPop grid. The primary result is:

```text
pct_affected = 100 * population_affected_mmi6 / population_total
```

An Admin area is deprived when its MMI VI exposure percentage is strictly
greater than the national population-weighted exposure percentage. The
continuous percentage is always retained because the relative binary rule can
hide materially affected areas after a widespread event.

## Principal outputs

- annual maximum-MMI GeoTIFF;
- MMI V, VI and VII binary masks;
- canonical administrative summary with threshold sensitivities and deprivation;
- complete considered/included/excluded event register;
- maximum-MMI and deprived-admin QC maps; and
- schema-valid provenance metadata and a human-readable source record.

## Limitations

Exposure is not confirmed damage, injury, displacement, or WASH disruption.
The method omits tsunami, liquefaction, landslides, fire and other secondary
hazards. WorldPop represents usual residential population, while ShakeMap
uncertainty varies with instrumental coverage, local geology and model support.

## Run example

```bash
wia-hazards run-earthquake \
  --iso3 MMR \
  --as-of-date 2025-12-31 \
  --worldpop-path data/population/mmr_pop_2025_CN_100m_R2025A_v1.tif \
  --admin-path data/cod-ab/global_admin_boundaries.gdb.zip \
  --config configs/earthquake.example.yml
```
