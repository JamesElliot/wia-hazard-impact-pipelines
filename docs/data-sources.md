# Data sources

## USGS earthquake catalogue and ShakeMap

The HI-EQ pipeline queries the public USGS FDSN event service and follows each
catalogue event's product metadata to the selected ShakeMap `grid.xml`. Raw
catalogue responses, event details, version identifiers, product URLs and
checksums are retained in the run directory. A successful empty result is
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
| Administrative boundaries | All hazards | GeoPackage, geodatabase, or supported archive with ISO3 and pcode fields | Record source release, admin level, and any boundary modifications. |
| WorldPop | All hazards | Country population GeoTIFF | Population is the reference grid for alignment and affected-population sums. |
| Copernicus `derived-drought-historical-monthly` | Drought | Downloaded through `cdsapi` | The implementation selects SPEI3 and requests the configured monthly window. |
| Copernicus `derived-utci-historical` | Heat | Downloaded through `cdsapi` | The implementation derives daily maximum UTCI before consecutive-day tests. |
| EODC STAC `GFM` collection | Flood | Remote STAC assets | The default asset is `ensemble_flood_extent`. |
| NOAA NCEI IBTrACS v4 | Cyclone | Local CSV (`last3years` or `since1980`) | Observed track points and quadrant wind radii define the baseline event footprints. |
| GDACS tropical-cyclone wind buffers | Cyclone fallback | Remote API or local GeoPackage | Used only when an expected IBTrACS contour does not meet the configured completeness threshold. |
| ACLED event data | Violence | User-supplied CSV | Raw records are licensed content and must never be committed or redistributed. |

## Local layout

```text
data/
├── cod-ab/
├── cyclone/
├── population/
└── violence/
```

All files below `data/` are ignored. Example configuration and manifests live
in `configs/` so that paths and run parameters can be shared without sharing
the underlying data.

## Provenance requirements

Every production run should record, at minimum:

- source name and product identifier;
- release/version or access date;
- local filename or remote asset identifier;
- spatial resolution, CRS, units, and nodata value;
- any filtering, clipping, resampling, or boundary changes;
- applicable licence and required attribution.
