# Output contract

Each run lives at `outputs/<ISO3>/<WINDOW>/<hazard>/`, where `WINDOW` is
`<as_of_date>_m<lookback_months>` (e.g. `2024-12-31_m12`) and `hazard` is one
of `flood`, `heat`, `cold`, `drought`, `earthquake`, `cyclone`, `violence`,
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

### Administrative boundary provenance

Every hazard run records an `admin_source` block in `run_metadata.json`,
schema-validated against `schemas/run_metadata.schema.json`:

| Field | Meaning |
|---|---|
| `authority` | Boundary-set publisher (e.g. `COD`, `GADM`, `NSO`) |
| `vintage` | `<AUTHORITY><YYYY-MM>` token, e.g. `COD2026-06` |
| `access_date` | Date the boundary set was obtained |
| `path` | Resolved absolute path to the admin dataset used |
| `sha256` | Content checksum of the admin dataset |
| `admin_level` | Admin level aggregated to |
| `unit_count` | Number of admin units in the aggregation |
| `pcode_field` | P-code column used for the join |

The vintage token also appears in every emitted table filename, so
provenance survives a table being copied out of its run directory. A run
fails fast at start if the admin dataset's sidecar `admin_source.json`
manifest (adjacent to the resolved admin path, e.g.
`data/cod-ab/admin_source.json`) is missing or malformed — see
`core/assets.py:load_admin_source_manifest`. `admin_source` is optional in
the schema so historical runs that predate this field remain valid; a
publication-readiness check can additionally require it via
`wia-hazards validate-metadata --require-admin-source`.

### Input dataset provenance (`data_sources`)

`admin_source` covers the boundary set only. Since schema 1.2.0 every hazard run also writes a
`data_sources` array to `run_metadata.json`: one entry per input dataset the run used, holding the
facts a data credit needs. The array is optional in the schema, so older runs still validate.
Each entry must state `dataset`, `provider`, `access_date` and `licence`; a value that is not known
or not stated is an explicit `null`, never a missing key.

| Field | Meaning |
|---|---|
| `dataset` | Canonical name, e.g. `ERA5-HEAT (UTCI)`, `IBTrACS`, `WorldPop Global 2015-2030 (constrained, 100 m)` |
| `provider` | Publisher |
| `catalogue_id` | Machine identifier where one exists (CDS dataset id, STAC collection) |
| `version` | Release or version as the provider states it or the request used, e.g. `1_1`, `v04r01`, `R2025A v1` |
| `doi` / `url` | DOI (preferred) and product URL |
| `access_date` | Date the data were **retrieved**, never the run date. `null` when unknown, with a warning in the log and in `metadata["warnings"]` (stage `data_sources`) |
| `period` | `{start, end}` of the window used |
| `area` | Country code, or `{iso3, bbox_nwse}` for a CDS request |
| `selection` | Filters applied: variable and statistic, thresholds, event types, product tiers, event ids and versions |
| `sha256` | Checksum of the local input file, where there is one |
| `licence`, `licence_url` | Licence or terms as the provider states them (short text and the terms URL). `null` means no licence is recorded; `notes` then says whether the provider states none or the terms are unconfirmed |
| `attribution` | The provider's required credit wording, with the year filled from `access_date` (`[Year]` when unknown) |
| `notes` | Set where terms are unconfirmed or a provider states no licence; read it before publishing a credit |

`licence` is descriptive. It is copied from the provider and is not legal advice. Entries never hold
local paths or credentials; a check in `core/data_sources.py` rejects both.

Entries per pipeline: heat and cold (ERA5-HEAT/UTCI, WorldPop, COD-AB), drought (ERA5-Drought/SPEI,
WorldPop, COD-AB), hydrological drought (GloFAS, HydroRIVERS, WorldPop, COD-AB), flood (GFM, WorldPop,
COD-AB), violence (ACLED, WorldPop, COD-AB), cyclone (IBTrACS, WorldPop, COD-AB, plus GDACS only when
the fallback was used), earthquake (USGS ShakeMap, WorldPop, COD-AB).

#### Where the access date comes from

- **Downloads made by this repository** (CDS, EWDS, WorldPop batch download, USGS) write a
  `<file>.retrieved.json` record beside the file with the retrieval date. A CDS run states the **latest**
  retrieval date over its monthly downloads, and only when every download has a record. The per-month
  detail stays in the CDS manifest CSV.
- **GFM** uses the date of the STAC query, which is saved beside the flood-days raster
  (`<raster>.retrieved.json`) so a run that reuses the raster reports the original date. A raster made
  before this change has no record, so its date is `null`.
- **GDACS** (cyclone fallback) keeps its retrieval date beside the cached fallback files, so cache hits
  report it.
- **Cyclone bulk WorldPop downloads** already wrote `<file>.source.json` with `retrieved_utc`; that date is
  used when there is no `.retrieved.json`.
- **User-supplied files** (WorldPop, ACLED, IBTrACS, HydroRIVERS) have no retrieval record unless you make
  one. Use `wia-hazards record-retrieval <file>... --date YYYY-MM-DD`, or pass `--acled-access-date` /
  `--ibtracs-access-date`. An ACLED export named `ACLED Data_YYYY-MM-DD...` supplies its own date.
- **Runs made before this change** left cached downloads with no record, so their `access_date` is `null`.
  If you know when they were fetched, back-fill with `record-retrieval` (for example over
  `outputs/_cache/heat/AFG/cds_raw/*.zip`) and re-run.

#### Provider facts in the registry

DOIs, licences and attribution wording live in `REGISTRY` in `core/data_sources.py`, read from each
provider's catalogue or terms page on 2026-09-29 (CDS/EWDS catalogue API, the Copernicus and CEMS licence
PDFs, NOAA NCEI, USGS, WorldPop, HydroSHEDS, ACLED). Re-check the registry when a provider changes its terms.
Three cases carry a `notes` warning:

- **GFM:** the EODC STAC record says `proprietary`, which only means a non-SPDX licence and is not
  necessarily closed data. The GFM Product User Manual's CC BY 4.0 statement covers the document, not the
  data. The data terms and attribution wording are unconfirmed.
- **GDACS** (used only for the cyclone fallback): its terms of use state no licence and no attribution
  wording, only disclaimers, so `licence` is null. Some third-party catalogues list CC BY 4.0; GDACS does
  not confirm it.
- **Boundary sets:** HDX sets the licence per dataset, so it is read from the boundary set's own
  `admin_source.json` (`licence`, `licence_url`, `dataset_url`, `terms_checked_on`), not from the registry.
  The shared global archive records CC BY-IGO (HDX `cod-ab-global`, checked 2026-09-29). A manifest without
  those fields gives `licence: null` and a note. Per-country override manifests under `data/cod-ab/` are
  local files: add the fields there. HDX lists CC BY-IGO for `cod-ab-mdg`, `-mli`, `-sdn`, `-moz` and
  `-lbn` on the same date.
