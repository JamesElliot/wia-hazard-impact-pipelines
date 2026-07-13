# Extreme heat indicator (UTCI)

## Definition

The reference implementation downloads the Copernicus
`derived-utci-historical` product through CDS, derives daily maximum UTCI, and
tests whether a pixel exceeds a threshold for a consecutive run of days.

Default thresholds are 32°C, 38°C, and 46°C. The default duration is three
consecutive days. A pixel is affected for a threshold when at least one such
run occurs in the configured analysis window. Affected population is WorldPop
on the resulting binary mask.

## Principal outputs

- one binary mask and affected-population raster per threshold;
- administrative total and percentage exposed per threshold;
- coverage, download, progress, and parity reports;
- standardized run metadata.

## Important implementation choices

- Kelvin-like values are converted to Celsius when detected.
- Daily maximum selection and time-zone/day boundaries must be preserved in
  the Earth Engine translation.
- Missing UTCI observations mean missing data, not zero heat.
- Threshold comparison, rolling-window boundaries, and inclusivity require
  explicit cross-platform tests.
