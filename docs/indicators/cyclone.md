# Tropical-cyclone indicator (HI-06)

## Definition

The reference implementation selects tropical-cyclone observations in the
configured rolling window and constructs geodesic swaths from IBTrACS quadrant
wind radii. A population cell is affected when it falls inside the union of
observed 34-knot (63 km/h) swaths. The 50- and 64-knot contours are retained as
93 and 119 km/h severity bands.

The implementation transforms boundaries and footprints to the native
WorldPop grid instead of resampling population counts. Numerator and
denominator therefore use the same cells. Results are aggregated to the admin
level configured for the run.

## Completeness and GDACS fallback

For each storm and contour, completeness is the fraction of in-window track
observations with at least one valid quadrant radius. The default minimum is
50%. When an expected contour is incomplete, the run fails unless one of these
explicit alternatives applies:

- a local GDACS footprint keyed by IBTrACS storm ID is supplied;
- `--gdacs-auto` matches the storm by normalized name and overlapping dates,
  then retrieves consolidated GDACS 60/90/120 km/h wind buffers; or
- `footprint.allow_incomplete` is deliberately enabled, producing flagged
  partial results.

GDACS native thresholds are mapped to 63/93/119 km/h and both values are kept
in provenance. Forecast cones, track lines, and centroids are not ingested.

## Principal outputs

- a multi-band 63/93/119 km/h mask on the WorldPop grid;
- an admin summary table with population totals, affected population, percent
  affected, storm count, severity statistics, and quality flags;
- storm and GDACS audit tables;
- per-storm/per-threshold footprint vectors;
- a storm-track and affected-population map;
- an admin-level percentage-affected choropleth; and
- schema-valid `run_metadata.json` with input checksums and artifacts.

## Important implementation choices

- Wind radii from different agencies are not mixed at one observation. A
  complete family is selected, preferring USA radii and then WMO-agency fields.
- Track interpolation is geodesic and limited by both spatial spacing and a
  maximum time gap (12 hours by default).
- The assigned admin population must match the source raster total within 2%
  by default, catching wrong-country rasters and boundary mismatches.
- Rainfall and storm surge are excluded to avoid overlap with the flood
  indicator.
- A zero-event result is distinct from a long-term country applicability
  decision, which remains an upstream scope check.

## Run example

```bash
wia-hazards run-cyclone \
  --iso3 MOZ \
  --as-of-date 2026-03-31 \
  --lookback-months 12 \
  --ibtracs-path data/cyclone/ibtracs.since1980.list.v04r01.csv \
  --worldpop-path data/population/moz_pop_2025_CN_100m_R2025A_v1.tif \
  --admin-path data/cod-ab/moz_adm2.gpkg \
  --config configs/cyclone.example.yml \
  --gdacs-auto
```
