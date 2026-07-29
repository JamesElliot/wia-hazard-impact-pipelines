# Output contract

Each run lives at `outputs/<ISO3>/<WINDOW>/<hazard>/`, where `WINDOW` is
`<as_of_date>_m<lookback_months>` (e.g. `2024-12-31_m12`) and `hazard` is one
of `flood`, `heat`, `drought`, `earthquake`, `cyclone`, `violence`,
`hydrodrought`. This
country-first shape lets a run's outputs be copied or symlinked directly into
a WIA country folder. Within that directory, each run creates these canonical
folders:

```text
raw/
intermediate/
rasters/
tables/
qc/
maps/
logs/
run_metadata.json
```

Hazard modules retain compatibility filenames and columns, but every Python
pipeline now also emits the shared contract below. Google Earth Engine outputs
must provide the same canonical fields.

## Administrative summary fields

| Field | Meaning |
|---|---|
| `iso3` | Uppercase ISO3 country code |
| `admin_level` | Administrative level used for aggregation |
| `admin_pcode` | Stable pcode at that level |
| `period_start` | Inclusive analysis start date |
| `period_end` | Inclusive analysis end date |
| `hazard` | Stable hazard identifier |
| `method_version` | Version of the indicator definition |
| `population_total` | Population on valid reference-grid cells in the admin area |
| `population_affected` | Population on pixels satisfying the hazard rule |
| `pct_affected` | `100 * population_affected / population_total` |
| `hazard_data_coverage` | Share of the relevant area or population with hazard observations |
| `population_data_coverage` | Share of the administrative area covered by the population grid |

Hazard-specific severity columns are allowed, but their units and denominator
must be documented. Existing hazard-specific names such as `pop_total`,
`pop_affected_flood`, and `pct_exposed_abs32c` remain as compatibility aliases.
For multi-threshold hazards, the canonical `population_affected` and
`pct_affected` fields use the documented reporting threshold; all threshold
columns remain available. Hydrological drought additionally stages a
persistence variant of each threshold (`..._p2m` = at least 2 consecutive
months), alongside the any-occurrence column; see
[`docs/indicators/hydrodrought-glofas-sri.md`](indicators/hydrodrought-glofas-sri.md).

## Raster requirements

Every published raster must record:

- band name and meaning;
- CRS, affine transform, dimensions, and pixel size;
- dtype, units, and nodata value;
- resampling method used during alignment;
- whether masked pixels mean zero hazard or missing observation;
- the population grid release used as the reference.

Binary hazard masks use 1 for affected and 0 for observed/not affected.
Missing hazard observations must not silently become zero unless that behavior
is explicitly part of the indicator definition.

## Indicator maps

Every hazard writes two PNGs to `maps/`: a footprint/extent map showing where
the hazard occurred overlaid on affected population, and an admin-level
choropleth of `pct_affected`. Both are registered as artifacts in
`run_metadata.json`. Where a natural severity/intensity value is already
computed by the pipeline (e.g. flood-day counts, MMI intensity, wind-speed
bands), the footprint map colors by that value instead of a flat binary mask;
otherwise a binary affected/not-affected map is used.

## Metadata

`run_metadata.json` is validated against
`schemas/run_metadata.schema.json`. Pipeline runs record run parameters,
canonical paths, emitted artifacts, stable pipeline and method-version IDs, and
the affected-population rule. Dataset-specific provenance remains mandatory for
production publication even where an upstream source cannot expose it
programmatically.
