# Hydrological drought indicator (GloFAS / SRI)

## Definition

The reference implementation downloads Copernicus GloFAS historical river
discharge (`cems-glofas-historical`, variable `dis24`) through the Early
Warning Data Store (EWDS), reduces it to monthly means, and standardizes a
rolling 3-month accumulation (SRI3) against a fitted baseline distribution --
the same accumulation convention this repo already uses for SPEI3 (HI-07).

Default thresholds are −1.0, −1.5, and −2.0. For each threshold, a river reach
is flagged when its SRI3 crosses the threshold in the analysis window, in two
variants:

- **any-occurrence**: SRI3 ≤ threshold in any reported month;
- **persistence**: SRI3 ≤ threshold for at least 2 consecutive months.

The default reporting variant is the persistence mask at −1.5
(`rel_sri_le_m1p5_p2m`). 30 consecutive days (the literal duration rule in the
source methodology note) is not resolvable once the series is accumulated
monthly, so persistence is translated to "at least 2 consecutive months," the
natural analogue at this cadence -- see
`docs/hydrodrought-implementation-plan.md`.

**Open methodological question — variable choice (discharge vs. runoff):**
`HI_Hydrological_Drought_GloFAS_Pipeline_Development_Plan.md` (the source
methodology note) states a preference for GloFAS **runoff**
(`runoff_water_equivalent`), falling back to river discharge only if runoff is
not distributed as an accessible variable. The live EWDS catalogue has since
been confirmed to distribute `runoff_water_equivalent` (see
`docs/hydrodrought-implementation-plan.md`), i.e. the note's own fallback
condition does not hold. This reference implementation nonetheless defaults
to discharge (`dis24`, via `cems-glofas-historical`) rather than runoff,
because discharge is what was implemented and tested first — not because a
methodology review concluded discharge is the better choice. Discharge-based
SRI and runoff-based SRI are not numerically interchangeable, so this is a
real, unresolved deviation from the note's stated preference, not a
documentation-only distinction. WIA methodology review should explicitly
ratify discharge vs. runoff before this indicator is promoted past prototype
status; if runoff is chosen instead, every hydrodrought run must be
re-baselined and re-validated (see the Somalia pilot in
`docs/hydrodrought-implementation-plan.md`) rather than assumed equivalent.

## River-corridor population attribution

GloFAS is a river-network model: values are meaningful on the river grid, not
uniformly across every land pixel. Resampling the sparse discharge grid onto
WorldPop would misattribute a reach's drought status to populations far from
that reach. Instead:

1. HydroRIVERS reaches are clipped to the country and buffered into a
   corridor (a flat width by default, optionally scaled by Strahler order).
2. Every WorldPop pixel within some corridor is assigned to its *nearest*
   reach via a raster distance transform (`core.rivers`), not resampling.
3. A pixel is affected only if it falls within a corridor **and** its nearest
   reach's SRI3 crosses the threshold. Pixels outside every corridor are not
   affected by this hazard (same semantics as a SPEI pixel that never crosses
   threshold) but still count in the population denominator.

The corridor width, reach count, and Strahler-order rule are recorded in
`run_metadata.json`'s `river_corridor` block for every run.

## Principal outputs

- one binary mask and affected-population raster per threshold x duration
  variant (6 total: 3 thresholds x any-occurrence/persistence);
- administrative total and percentage affected per variant;
- baseline-fit diagnostics (gamma vs. empirical cell counts) in the QC table;
- monthly download manifests (baseline and window) and coverage/parity checks;
- standardized run metadata.

## Important implementation choices

- SRI accumulation is monthly (SRI-3), not raw daily GloFAS values, matching
  this repo's SPEI-3 convention and the WMO-1173 handbook's standard practice.
- The baseline distribution is a mixed point-mass-at-zero + gamma fit per
  grid cell, falling back to an empirical (Weibull plotting-position)
  distribution for cells with too few nonzero baseline observations
  (intermittent/zero-flow rivers) -- see `core.standardize`.
- Missing observations mean missing data, not absence of drought.
- The corridor width is a real, documented methodological assumption, not a
  verified physical boundary; it should be validated against observed WASH
  impacts before this indicator is treated as production-ready (see the
  validation plan in `docs/hydrodrought-implementation-plan.md`).
- GloFAS request field names and the `cems-glofas-historical` dataset ID have
  been confirmed against the live EWDS process catalogue (`GET
  /retrieve/v1/processes/cems-glofas-historical`), and a real month of data
  has been downloaded and processed end-to-end for Somalia. The catalogue
  also confirmed `runoff_water_equivalent` is available as an alternative
  variable to the discharge-based default used here.
- The EWDS response for this dataset is a raw NetCDF file (not a zip) with a
  `valid_time` dimension (not `time`); both are handled explicitly rather
  than assumed to match the SPEI/UTCI CDS response shape.

## Relationship to the existing SPEI drought indicator (HI-07)

This is a parallel `hydrodrought` hazard, not a replacement for the existing
SPEI3-based `drought` (HI-07) hazard. Both can be run and compared; promoting
hydrological drought to drive HI-07 (or assigning it its own HI slot) is a
decision for after the validation phase, not before.
