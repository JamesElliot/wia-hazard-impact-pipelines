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

## Hazard-specific considerations

The correspondence table and design rules above assume a raster
threshold-and-mask pipeline: load a hazard image, compare against a
threshold, multiply by population, `reduceRegions`. Five of the seven
hazards (flood, drought/SPEI, heat/UTCI, cyclone, earthquake) fit that shape
directly. Two do not, because their core operation is vector geometry
(buffer + union over a point/line feature set), not a raster comparison —
translating them naively would risk hitting GEE's per-feature
vertex/computation-timeout limits at realistic event/reach counts:

- **Violence (ACLED)**: the local implementation buffers each event point by
  its type-specific radius (5/2/1 km) and unions the buffers before
  rasterizing/counting. A literal per-event `ee.Geometry.buffer()` +
  `ee.FeatureCollection` union over a country-year's ACLED events is exactly
  the per-feature-geometry-operation pattern GEE handles awkwardly at scale.
  Two viable strategies: (a) precompute the buffered/unioned event-density
  surface outside GEE and import it as a static raster asset per run, or (b)
  investigate whether `ee.FeatureCollection.distance()` or a vectorized
  kernel-density image reducer can reproduce the same per-pixel event-count
  semantics without an explicit per-feature buffer/union step. Neither has
  been evaluated against this repo's actual output for parity; this is an
  open design question for whoever does the translation, not a decided plan.
- **Hydrological drought (GloFAS/SRI, hydrodrought)**: population is
  attributed to river reaches via a nearest-reach raster distance transform
  over a buffered `HydroRIVERS` line-feature corridor (`core/rivers.py`), not
  a direct raster comparison. The GEE equivalent would need either (a) a
  precomputed corridor/nearest-reach-assignment raster imported as a static
  asset (mirroring the local `core.rivers` output), since GEE has no direct
  distance-transform-to-nearest-line-feature primitive at this scale, or (b)
  reformulating the corridor assignment as a sequence of `ee.Image.distance()`
  calls per reach group, which does not obviously preserve the same
  "population served by its single nearest reach" semantics as the local
  vectorized distance transform. Also unresolved, and worth deciding together
  with METHOD-005 (the discharge-vs-runoff variable question), since both
  affect what a GEE port of hydrodrought would actually ingest.

Neither strategy above should be assumed correct without a parity check
against this repo's own output for at least one real country, the same as
every other hazard's parity process below.

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
