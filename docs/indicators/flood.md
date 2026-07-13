# Flood indicator

## Definition

The reference implementation queries the Copernicus Global Flood Monitoring
`GFM` STAC collection through the EODC endpoint and uses the
`ensemble_flood_extent` asset. Daily observations are accumulated into a
flooded-day count on the WorldPop reference grid.

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
  failure bound used to distinguish warnings from unusable coverage.
- Flood extent resampling and same-day item handling must be matched explicitly
  in the Earth Engine implementation.

## Limitations to resolve

Coverage bounds do not guarantee valid observations for every pixel and day.
Cloud/sensor availability, duplicate acquisitions, mixed native grids, and the
meaning of missing flood pixels require explicit parity tests.
