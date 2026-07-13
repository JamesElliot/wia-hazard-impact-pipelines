# Google Earth Engine handoff

The Python pipelines are a reference implementation for indicator semantics.
The Earth Engine workflow should reproduce those semantics rather than mirror
the local file-processing code line by line.

## Processing correspondence

| Python operation | Earth Engine equivalent |
|---|---|
| Load and filter admin polygons | Configured `ee.FeatureCollection` and ISO/admin filters |
| Align hazard data to WorldPop | Explicit projection/scale rules on image operations and reducers |
| Build a threshold mask | Image comparison plus documented mask handling |
| Multiply mask by population | Multi-band image containing population, affected population, and severity components |
| Aggregate each admin polygon | One `reduceRegions` operation per hazard product or compatible band stack |
| Write CSV and metadata | Export one table per hazard/run plus a machine-readable run manifest |

## Required design rules

1. Use `reduceRegions` for the full administrative feature collection instead
   of issuing one reduction per feature.
2. Stack compatible sum components as bands so one pixel traversal produces
   total population, affected population, weighted severity, and coverage.
3. Treat nodata explicitly. Distinguish “no hazard” from “no observation.”
4. Export component sums as well as derived percentages so results can be
   audited outside Earth Engine.
5. Record asset IDs, image collection filters, projection, scale, reducer
   settings, and method version in the run manifest.
6. Keep GEE project IDs, asset IDs, admin fields, and export destinations in
   configuration rather than source code.

## Parity process

For each hazard, select a small country/window that both systems can process.
Compare:

- analysis dates and source item counts;
- affected-pixel logic;
- total and affected population by admin area;
- coverage metrics;
- national sums and tolerance-adjusted raster statistics.

Differences caused by projection, resampling, pixel inclusion, or
`all_touched` behavior must be measured and documented rather than hidden by a
wide tolerance.
