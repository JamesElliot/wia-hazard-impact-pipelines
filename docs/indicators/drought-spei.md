# Drought indicator (SPEI3)

## Definition

The reference implementation downloads the Copernicus
`derived-drought-historical-monthly` product through CDS and selects the
three-month Standardized Precipitation Evapotranspiration Index (SPEI3).

Default thresholds are −1.0, −1.5, and −2.0. For each threshold, a pixel is
affected when any month in the configured analysis window has:

```text
SPEI3 <= threshold
```

The default reporting threshold is −1.5. Affected population is WorldPop on
the binary “any qualifying month” mask.

## Principal outputs

- one binary mask and affected-population raster per threshold;
- administrative total and percentage affected per threshold;
- monthly download manifest and coverage/parity checks;
- standardized run metadata.

## Important implementation choices

- The temporal aggregation is occurrence, not average intensity or duration.
- Missing observations mean missing data, not absence of drought.
- SPEI variable selection, scale, calendar, and monthly timestamp handling
  must be verified against the Earth Engine source asset.

## Future method work

The repository tracks a planned continuous/intensity product. It should not be
presented as part of the current affected-population definition until the
method, units, and weighting rule are approved.
