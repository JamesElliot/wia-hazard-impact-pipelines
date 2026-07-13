# Violence indicator (ACLED proximity)

## Definition

The reference implementation filters a user-supplied licensed ACLED export to
the requested country, dates, and included event types. Each retained event is
buffered by a rule based on event type and, for violence against civilians,
fatalities. Overlapping buffers are rasterized additively on the WorldPop grid
to produce event count.

Default buffer distances are:

| Event type | Buffer |
|---|---:|
| Battles | 5 km |
| Explosions/Remote violence | 5 km |
| Violence against civilians with one or more fatalities | 5 km |
| Violence against civilians with zero fatalities | 2 km |
| Riots | 2 km |
| Protests | 1 km |

Protests are supported but excluded from the default included-event list. The
default binary mask marks pixels with one or more buffered events as affected.

## Principal outputs

- additive event-count raster;
- derived binary proximity mask;
- affected-population raster;
- population-weighted event-count raster and admin summaries;
- footprint and QC artifacts;
- standardized run metadata.

## Important implementation choices

- Raw ACLED records are not distributable through this repository.
- Buffering must use a suitable metric CRS and record the CRS used.
- The local implementation defaults to all-touched rasterization; Earth Engine
  geometry/pixel inclusion differences require parity measurement.
- Overlapping buffers increase event count but do not double-count population
  in the binary affected-population estimate.

## Interpretation

This is a proximity/exposure indicator, not an estimate that every person in a
buffer directly experienced violence. Results depend strongly on geolocation,
event classification, buffer assumptions, reporting coverage, and the chosen
time window.
