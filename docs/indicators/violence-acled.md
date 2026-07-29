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

## Input file discovery

ACLED exports are obtained manually (there is no automated download step),
so a given export's filename depends entirely on how and when it was
downloaded — there is no standard filename to rely on. **Always pass
`--acled-csv <path>` explicitly** when triggering the pipeline, pointing at
the specific export file you intend to use for that run.

If `--acled-csv` is omitted, the pipeline falls back to guessing a file under
`data/violence/`: first an exact-match convention
(`acled_<iso3 lowercase>_<window_start no-dashes>-<window_end no-dashes>.csv`,
e.g. `acled_grd_20250101-20251231.csv`), then two legacy notebook naming
patterns, then simply the most recently modified file matching
`acled_<iso3>_*.csv` in that directory. This fallback exists for
convenience/back-compatibility with older notebook runs and should not be
relied on for real runs — it can silently pick an export covering the wrong
dates or an out-of-date file if more than one export for the same country
exists locally. If no fallback candidate exists, the run fails with
`FileNotFoundError: Missing ACLED CSV`.

`event_type` values in the CSV must match ACLED's own schema strings exactly:
`Battles`, `Explosions/Remote violence`, `Violence against civilians`,
`Riots`, `Protests`. Any other value raises
`ValueError: Unsupported ACLED event_type for proximity buffer`.

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
