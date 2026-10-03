# Flood indicator

## Definition

The reference implementation queries the Copernicus Global Flood Monitoring
`GFM` STAC collection through the EODC endpoint and uses the
`ensemble_flood_extent` asset. Daily observations are accumulated into a
flooded-day count on the WorldPop reference grid.

All GFM tiles and acquisitions for the same UTC calendar day are mosaicked with
logical OR before the day count is incremented. Multiple acquisitions on one
day therefore cannot inflate the flooded-day duration.

A pixel is affected when:

```text
flood_days > flood_binary_threshold_days
```

The default threshold is zero, so one or more flooded days in the analysis
window marks the pixel as affected. Affected population is WorldPop multiplied
by this binary mask.

## Principal outputs

- flooded-day count raster;
- derived binary flood mask;
- affected-population raster;
- optional population-weighted flooded-day raster;
- administrative population and severity summaries;
- STAC and WorldPop coverage checks.

## Important implementation choices

- Default STAC endpoint: `https://stac.eodc.eu/api/v1`.
- Default WorldPop coverage threshold: 98%.
- Default STAC union-bounds coverage threshold: 99.999%, with a lower hard
  failure bound of 50% used to distinguish warnings from unusable coverage
  (coverage below 50% raises; coverage between 50% and 99.999% warns).
- Reused flood-days rasters: when `<ISO3>_flood_days_<start>_<end>.tif` already exists in the run
  folder it is reused and GFM is not queried again. A fresh query writes a
  `<raster>.coverage.json` sidecar (STAC union coverage, item count) next to the raster, and a
  reuse restates it in `preflight_coverage.flood_stac` (`coverage_recorded: true`). If the raster
  has no sidecar, coverage and the GFM retrieval date are unknown: `coverage_recorded` is false,
  the run records a warning, and `flood-postrun` reports WARN (not a 0% FAIL) for the STAC
  coverage check. Pass `--refresh-flood-days` to `run-flood` (or the script) to query GFM again and
  record both.
- Flood extent resampling and the UTC calendar-day mosaic must be matched
  explicitly in the Earth Engine implementation.

## Limitations to resolve

Coverage bounds do not guarantee valid observations for every pixel and day.
Cloud/sensor availability, duplicate acquisitions, mixed native grids, and the
meaning of missing flood pixels require explicit parity tests.
