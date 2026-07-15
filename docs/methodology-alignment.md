# Cross-hazard methodology alignment

All five pipelines implement the same reporting sequence while retaining the
science appropriate to each hazard:

1. validate an ISO3, inclusive analysis window, admin level, and source inputs;
2. use the country WorldPop raster as the reference grid and denominator;
3. align or rasterize the hazard on that grid without resampling population counts;
4. evaluate a documented binary affected/not-affected rule;
5. multiply the binary mask by WorldPop, so overlapping events or thresholds do
   not double-count affected population;
6. aggregate totals and affected population to the configured admin level; and
7. emit the common administrative table, raster/QC artifacts, and validated run metadata.

## Method registry

Stable identifiers, method versions, and the population rule are defined once
in `wia_pipelines.core.pipeline.HAZARD_METHODS`. Pipelines must use that registry
rather than defining their own reporting identity.

| Hazard ID | Pipeline ID | Default reporting rule |
|---|---|---|
| `drought` | `water_scarcity_spei3` | Any month with SPEI3 ≤ −1.5 |
| `heat` | `extreme_heat_utci` | UTCI > 32°C for at least three consecutive days |
| `flood` | `gfm_flood` | Flooded-day count > 0 |
| `cyclone` | `cyclone_ibtracs_wind_radii` | Inside the observed 63 km/h wind swath |
| `violence` | `violence_acled_proximity` | Buffered event count ≥ 1 |

The comparison operators are intentionally hazard-specific. Changing a
threshold, inclusivity rule, duration, footprint definition, population release,
or rasterization convention is a method change and requires a method-version
review plus a parity test.

## Shared versus hazard-specific behavior

Shared code owns run directories, metadata validation, artifact registration,
administrative contract fields, admin-level naming, population-grid alignment,
and common raster operations. Hazard modules own source retrieval, quality and
coverage interpretation, event/threshold logic, severity products, and source-
specific provenance.

Administrative population is assigned by pixel centre (`all_touched=False`) in
every pipeline. This prevents boundary cells being assigned differently across
hazards or counted in two adjacent units. Hazard-footprint rasterization remains
method-specific: for example, violence buffers use all-touched inclusion by
default, while cyclone wind swaths use pixel-centre inclusion.

Missing hazard observations are not equivalent to observed zero hazard. Each
pipeline must report coverage and preserve nodata through alignment whenever the
source exposes a reliable observation mask. A `NaN` coverage field means the
metric is not yet measurable from the source workflow; it does not mean 100%.

## Canonical threshold selection

Multi-threshold tables retain every threshold. The canonical cross-hazard
`population_affected` and `pct_affected` aliases use SPEI ≤ −1.5 for drought and
UTCI > 32°C for heat. Flood, cyclone, and violence have one primary reporting
threshold. See the individual indicator documents for secondary severity bands.
