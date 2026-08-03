# Data sources

## USGS earthquake catalogue and ShakeMap

The HI-EQ pipeline queries the public USGS FDSN event service and follows each
catalogue event's product metadata to the selected ShakeMap `grid.xml`. Raw
catalogue responses, event details, version identifiers, product URLs and
checksums are retained in the run directory and a shared USGS cache. A
successful empty result is
distinct from a network or product-retrieval failure. USGS products may be
revised, so published WIA runs should freeze and retain the retrieved inputs.

The default pipeline does not use smoothed visualization contours, reported
casualties, earthquake magnitude, or PAGER loss estimates as the exposure
footprint. PAGER is an optional external validation source.

External datasets are not distributed with this repository. Each user must
obtain the relevant source, record its version or access date, and comply with
the provider's current licence and attribution requirements.

| Input | Used by | Expected local form | Notes |
|---|---|---|---|
| Administrative boundaries | All hazards | GeoPackage, geodatabase, or supported archive with ISO3 and pcode fields | Requires a sidecar `admin_source.json` (authority/vintage/access_date) next to the dataset — see "Administrative boundary provenance" in `docs/output-contract.md`; a run fails fast without it. Per-country COD-AB overrides live under `data/cod-ab/<override-name>/` (e.g. `data/cod-ab/mli_sdn_moz_lbn/`) and take precedence over the shared global dataset for any ISO3 listed in that directory's `admin_source.json` `"countries"` block — see `core.assets.resolve_admin_path`. |
| WorldPop | All hazards | Country population GeoTIFF | Population is the reference grid for alignment and affected-population sums. |
| Copernicus `derived-drought-historical-monthly` | Drought | Downloaded through `cdsapi` | The implementation selects SPEI12 and requests the configured monthly window. |
| Copernicus `cems-glofas-historical` (river discharge) | Hydrological drought | Downloaded through `cdsapi` pointed at the Early Warning Data Store (EWDS), a separate endpoint/credential set from the classic CDS | Daily discharge is downloaded per month and reduced to monthly means before SRI standardization; requires `~/.ewdsapirc` (see below). |
| HydroRIVERS v1.0 | Hydrological drought | Local geodatabase (`data/HydroRIVERS_v10/`) | Defines the river-corridor buffer used to attribute GloFAS reach status to nearby population, instead of a naive raster resample. |
| Copernicus `derived-utci-historical` | Heat | Downloaded through `cdsapi` | The implementation derives daily maximum UTCI before consecutive-day tests. |
| EODC STAC `GFM` collection | Flood | Remote STAC assets | The default asset is `ensemble_flood_extent`. |
| NOAA NCEI IBTrACS v4 | Cyclone | Local CSV (`last3years` or `since1980`) | Observed track points and quadrant wind radii define the baseline event footprints. |
| GDACS tropical-cyclone wind buffers | Cyclone fallback | Remote API or local GeoPackage | Used only when an expected IBTrACS contour does not meet the configured completeness threshold. |
| ACLED event data | Violence | User-supplied CSV, downloaded manually (no fixed filename) — always pass `--acled-csv <path>` explicitly when running the pipeline; see `docs/indicators/violence-acled.md` for the fallback filename convention and required `event_type` values | Raw records are licensed content and must never be committed or redistributed. |

## Local layout

```text
data/
├── cod-ab/
├── cyclone/
├── population/
├── violence/
├── HydroRIVERS_v10/
└── HydroLAKES_polys_v10/
```

All files below `data/` are ignored. Example configuration and manifests live
in `configs/` so that paths and run parameters can be shared without sharing
the underlying data.

The single-run commands discover the shared admin, WorldPop, and IBTrACS assets
from this layout, so those paths do not need to be repeated in every shell
command. Explicit path flags remain available for nonstandard layouts.

Reusable network downloads are stored separately from source inputs:

```text
outputs/_cache/
├── _shared/
│   ├── gdacs/
│   └── usgs/
├── heat/
└── water_scarcity_spei12/
```

Run directories contain hard-linked or copied references to the exact cached
USGS/GDACS products they used. Delete the relevant cache entry or pass
`--refresh-cache` when intentionally retrieving an upstream revision.

## EWDS credentials (hydrological drought)

GloFAS historical is served from the Copernicus Early Warning Data Store
(EWDS), not the classic CDS instance already configured for SPEI/UTCI.
Configure a separate `~/.ewdsapirc` (same `url:`/`key:` format as
`~/.cdsapirc`), or set `EWDS_API_URL`/`EWDS_API_KEY`, or pass
`--ewds-url`/`--ewds-key` explicitly. Without one of these, `run-hydrodrought`
fails at the preflight step with a clear error rather than partway through a
large download. In practice, the EWDS personal access key is the same key as
the existing CDS account (only the `url:` differs), so `~/.ewdsapirc` can
just copy `~/.cdsapirc`'s key with `url: https://ewds.climate.copernicus.eu/api`.

## Provenance requirements

Every production run should record, at minimum:

- source name and product identifier;
- release/version or access date;
- local filename or remote asset identifier;
- spatial resolution, CRS, units, and nodata value;
- any filtering, clipping, resampling, or boundary changes;
- applicable licence and required attribution.
