# Troubleshooting

## CRS mismatch

Symptoms: empty masks, all-zero zonal results, or rasterisation failure.

Checks:

- Ensure administrative polygons are in a known CRS (often EPSG:4326) and are reprojected/aligned before rasterisation.
- Ensure any hazard rasters are resampled to the WorldPop grid before multiplication.

## Nodata handling

Symptoms: inflated/deflated population totals.

Checks:

- Confirm the WorldPop nodata value is converted to NaN before calculations.
- Confirm the mask is 0/1 (or otherwise documented) before applying.
