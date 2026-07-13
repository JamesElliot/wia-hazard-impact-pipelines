# Output contract

Each run creates a deterministic run directory with these canonical folders:

```text
raw/
intermediate/
rasters/
tables/
qc/
logs/
run_metadata.json
```

Hazard modules currently retain some compatibility filenames. The shared
contract below is the target for both Python and Google Earth Engine outputs.

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
must be documented. Existing hazard-specific column names will be normalized
to this contract in a later compatibility release.

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

## Metadata

`run_metadata.json` is validated against
`schemas/run_metadata.schema.json`. It records run parameters, canonical paths,
and emitted artifacts. Dataset provenance and method-version fields will be
made mandatory before the first stable release.
