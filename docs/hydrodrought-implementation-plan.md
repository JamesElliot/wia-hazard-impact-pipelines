# Implementation plan — HI hydrological drought (GloFAS / SRI)

This translates `HI_Hydrological_Drought_GloFAS_Pipeline_Development_Plan.md`
(the methodology note, written against a different repo's Excel/XML-surgery
architecture) into this repo's actual architecture: a `wia_pipelines.hazards`
module, the shared run-context/contract in `core/pipeline.py`, the CLI in
`cli.py`, and the doc set under `docs/`. Layers B/C from the original note
(staging into `_wia_staged/`, XML surgery into the WIA Data workbook) do not
exist here and are out of scope; this repo's "Layer B/C equivalent" is the
output contract in `docs/output-contract.md` plus `run_metadata.json`, which
already exists and needs no new work beyond registering the new hazard.

## 1. Fit to the existing architecture

| Original plan's layer | This repo's equivalent | New work |
|---|---|---|
| Layer A processor | `hazards/hydrodrought.py` (mirrors `hazards/spei.py`) | New pipeline |
| Layer B staging/registry | `core/pipeline.HAZARD_METHODS`, `config.SUPPORTED_HAZARDS`, `schemas/run_metadata.schema.json` | Register `hydrodrought` |
| Layer C workbook integration | Output-contract CSV under `outputs/<ISO3>/<WINDOW>/hydrodrought/tables/` (no workbook in this repo) | None — contract already generic |

Everything reuses the pattern documented in `docs/methodology-alignment.md`:
validate ISO3/window/admin level → WorldPop as reference grid and denominator
→ align hazard to that grid → binary affected/not-affected rule → multiply by
WorldPop → aggregate to admin level → emit table + rasters + QC + validated
metadata via `standardize_admin_summary`.

Hazard id: **`hydrodrought`** (not `drought`, which stays SPEI/HI‑07). This
is Decision 1(b) from the original note — parallel table, no change to the
existing SPEI path — made concrete as a second, independent hazard identifier
rather than a variant of the existing one.

## 2. Design decisions, resolved for this repo

| # | Decision | Resolution |
|---|---|---|
| 1 | Indicator slot | `hydrodrought` hazard id, fully parallel to `drought` (SPEI). No changes to `hazards/spei.py`. |
| 2 | Variable | GloFAS river discharge (`dis24`) from `cems-glofas-historical`, the natively distributed reanalysis variable — same choice the note makes as the fallback ("SSI on discharge"), taken as the primary path since discharge is unambiguously in the EWDS catalogue and runoff distribution is unverified. Documented as a substitution for the note's stated runoff preference. The variable name is a single config constant so it can be swapped once the catalogue is confirmed. |
| 3 | Product | GloFAS-ERA5 historical/reanalysis (`cems-glofas-historical`), matching the SPEI pipeline's own use of the historical/reanalysis CDS product for consistency. |
| 4 | Accumulation | Monthly SRI-3 by default (mirrors this repo's SPEI-3 convention exactly), accumulation period exposed as a parameter. |
| 5 | Threshold | Stage all three bands (`rel_sri_le_m1p0/m1p5/m2p0`), default reporting threshold `m1p5`, matching the SPEI pipeline's `default_threshold_key` pattern. |
| 6 | Duration | Stage both an any-occurrence and a ≥30-consecutive-day persistence footprint per threshold (6 mask variants total); default reporting mask is the **persistence** variant at `m1p5`, per the note's own recommendation. |
| 7 | Baseline | Configurable baseline window (default 1991–2020, clipped to whatever the downloaded record actually covers — GloFAS-ERA5 nominally starts 1979). Recorded in `run_metadata.json` and the QC table so a documented baseline follows every run. |
| 8 | GDO benchmark | Out of scope for the prototype; not blocking. Left as a follow-up validation task (§7). |

## 3. The one methodological risk that matters: river-cell → population

GloFAS values live on a river network, not uniformly across land. The note
flags this as the single biggest risk. This repo already has **HydroRIVERS**
and **HydroLAKES** (`data/HydroRIVERS_v10/`, `data/HydroLAKES_polys_v10/`) —
apparently staged for exactly this purpose — so the plan uses them directly
instead of naive resampling:

1. Load HydroRIVERS reaches (`HydroRIVERS_v10.gdb`) clipped to the country AOI.
2. Sample the native-resolution SRI grid at each reach (nearest grid cell to
   each reach vertex/midpoint) to get a per-reach SRI time series.
3. Build a **river corridor**: buffer each reach by a width driven by its
   `ORD_STRA` (Strahler order) or a flat default (configurable, e.g. 5 km),
   capturing the population plausibly served by that reach.
4. For every WorldPop pixel inside some corridor, assign the SRI status of
   its *nearest* reach (KD-tree nearest-reach assignment, not a raster
   resample of the sparse GloFAS grid). Pixels outside every corridor are
   simply not affected by this hazard (same semantics as a SPEI pixel that
   never crosses threshold) — they still count in the population denominator.
5. Record the corridor width, the Strahler-order rule, and reach count in
   `run_metadata.json` so the assumption is auditable per run (this is the
   sidecar-provenance requirement from the original note, folded into the
   existing metadata contract instead of a separate `.source.md` file).

This logic is pure/vector-only (geopandas + scipy KD-tree), so it is unit
testable on synthetic river/point data without a real HydroRIVERS extract or
network access — see §6.

**Verified against the real `data/HydroRIVERS_v10/HydroRIVERS_v10.gdb`**
(8.48M reaches globally): reading the layer with no bbox filter is
impractically slow (materializes every reach worldwide before clipping), so
`core.rivers.load_river_reaches` takes a `bbox` and pushes it down to
`geopandas.read_file(..., bbox=...)`. Confirmed this brings a real country
(Somalia) down to 43,587 reaches in ~0.5s, vs. an unfiltered read that did not
complete in a reasonable time.

## 4. New/changed modules

| File | Change |
|---|---|
| `src/wia_pipelines/core/standardize.py` *(new)* | SRI computation: monthly accumulation, mixed gamma + point-mass-at-zero fit (falls back to empirical/Weibull plotting position when gamma fit fails, e.g. intermittent rivers), transform to standard normal. Pure numpy/scipy, unit tested with synthetic series including zero-flow. |
| `src/wia_pipelines/core/rivers.py` *(new)* | River-corridor construction and nearest-reach pixel assignment, per §3. |
| `src/wia_pipelines/core/ewds.py` *(new)* | Thin EWDS download wrapper wrapping `cdsapi.Client(url=..., key=...)`, reading a dedicated `~/.ewdsapirc` (mirrors `~/.cdsapirc` format) so this doesn't collide with the existing CDS credentials already configured for SPEI/UTCI. Falls back to explicit `--ewds-url/--ewds-key` overrides. |
| `src/wia_pipelines/core/assets.py` | Add `resolve_hydrorivers_path` / `resolve_hydrolakes_path`, defaulting under `data/HydroRIVERS_v10/` and `data/HydroLAKES_polys_v10/`, following the existing `resolve_admin_path`/`resolve_ibtracs_path` pattern. |
| `src/wia_pipelines/hazards/hydrodrought.py` *(new)* | Main pipeline: acquire → SRI → footprint (6 mask variants) → river-corridor overlay → WorldPop → admin aggregation → `standardize_admin_summary`. Mirrors `hazards/spei.py` stage-by-stage. |
| `src/wia_pipelines/hazards/hydrodrought_visualize.py` *(new)* | Footprint + admin choropleth maps, mirrors `spei_visualize.py`. |
| `src/wia_pipelines/hazards/hydrodrought_parity.py` *(new)* | Postrun parity checks, mirrors `spei_parity.py`. |
| `src/wia_pipelines/hazards/coverage_checks.py` | Add `glofas_sample_request` alongside the existing `spei_sample_request`/`utci_sample_request`, for preflight single-month coverage checks against the country bbox. |
| `src/wia_pipelines/core/pipeline.py` | Register `hydrodrought` in `HAZARD_METHODS`. |
| `src/wia_pipelines/config.py` | Add `"hydrodrought"` to `SUPPORTED_HAZARDS`. |
| `schemas/run_metadata.schema.json` | Add `"hydrodrought"` to the `run_config.hazard` enum. |
| `src/wia_pipelines/cli.py` | Add `run-hydrodrought` and `hydrodrought-postrun` subcommands, mirroring `run-spei`/`spei-postrun`. |
| `scripts/run_hydrodrought_pipeline.py` *(new)* | Headless script wrapper, mirrors `scripts/run_spei_pipeline.py`. |
| `src/wia_pipelines/batch/execute.py` | Add `hydrodrought` to `PIPELINES` and a default command template, so it can join `batch-run` alongside spei/utci/flood/violence. **Not** wiring it into `batch/readiness.py`/`batch/preflight.py`'s hazard-specific coverage checks in this pass — those are coupled to the four existing hazards' bespoke preflight logic; for the prototype, per-country runs are driven directly (same pattern already used for the VCT/GRD admin1 batches), not through `batch-preflight`. |
| `docs/output-contract.md`, `docs/data-sources.md`, `docs/methodology-alignment.md`, `README.md` | Add `hydrodrought` rows to the existing hazard tables. |
| `docs/indicators/hydrodrought-glofas-sri.md` *(new)* | Indicator doc, mirrors `docs/indicators/drought-spei.md`. |
| `pyproject.toml`, `environment.yaml` | Add `scipy` (needed for the gamma fit; not currently a dependency). |

## 5. Output schema

Same shape as SPEI's table, extended with the persistence variant, following
the note's §7 exactly:

```
adm{L}_pcode, adm{L}_name_en, ..., pop_total,
pop_affected_rel_sri_le_m1p0,      pct_affected_rel_sri_le_m1p0,
pop_affected_rel_sri_le_m1p5,      pct_affected_rel_sri_le_m1p5,
pop_affected_rel_sri_le_m2p0,      pct_affected_rel_sri_le_m2p0,
pop_affected_rel_sri_le_m1p0_p30,  pct_affected_rel_sri_le_m1p0_p30,
pop_affected_rel_sri_le_m1p5_p30,  pct_affected_rel_sri_le_m1p5_p30,
pop_affected_rel_sri_le_m2p0_p30,  pct_affected_rel_sri_le_m2p0_p30,
iso3, admin_level, admin_pcode, period_start, period_end, hazard,
method_version, population_total, population_affected, pct_affected,
hazard_data_coverage, population_data_coverage
```

Default reporting column: `pct_affected_rel_sri_le_m1p5_p30` (severe +
persistence), matching the note's recommendation.

## 6. Testing strategy (no network / no real GloFAS download required)

- `tests/test_core_standardize.py`: SRI math on synthetic monthly series,
  including an all-zero-flow case (gamma-fit fallback) and a normal case
  (verify standardization against `scipy.stats.norm.ppf` by hand).
- `tests/test_core_rivers.py`: corridor buffering + nearest-reach assignment
  on synthetic `LineString` reaches and a small pixel grid — verifies pixels
  outside every corridor are excluded and pixels near two reaches get the
  nearer one.
- `tests/test_hazard_hydrodrought.py`: window calculation, run-context
  build, and geography prep — mirrors `tests/test_hazard_spei.py` (skips the
  geospatial-stack-dependent class if the deps aren't importable, same as
  today).
- `tests/test_config.py`, `tests/test_core_pipeline.py`: extend existing
  parametrized assertions to include `hydrodrought`.
- No integration test hits EWDS for real — that requires live credentials
  (see §7, open item) and is out of scope for unit tests, same as SPEI/UTCI's
  CDS calls are excluded from the default contributor loop per `README.md`.

## 7. Catalogue verification (done) and remaining open items

§7 originally listed EWDS credentials and catalogue confirmation as open
items blocking a real run. Both are now resolved:

- **EWDS credentials work.** The EWDS account uses the same personal access
  key as the existing CDS account. `~/.ewdsapirc` is configured
  (`url: https://ewds.climate.copernicus.eu/api`, same key as `~/.cdsapirc`).
- **`cems-glofas-historical` is confirmed live and correct.** Queried
  `GET {url}/retrieve/v1/processes` directly: it is a real process ID,
  distinct from `efas-historical` (European Flood Awareness System —
  Europe-only, would not cover any of the 12 priority countries below). Its
  input schema was fetched and matches this code's request fields exactly:
  `system_version` (`version_2_1`/`version_3_1`/`version_4_0`),
  `hydrological_model` (`htessel_lisflood`/`lisflood`), `product_type`
  (`consolidated`/`intermediate`), `variable` — which also confirmed
  **`runoff_water_equivalent` is available**, resolving Decision 2 from the
  original methodology note in the note's own preferred direction (runoff is
  distributed after all; this pipeline still defaults to
  `river_discharge_in_the_last_24_hours` since that's what was implemented
  and tested, but switching the default variable is now a one-line change,
  not a catalogue question).
- **A real download was executed end-to-end** (one day, then one full month,
  for Somalia) and caught two real bugs the design couldn't have found any
  other way, both now fixed:
  1. The response is a **raw NetCDF file, not a zip** (unlike SPEI/UTCI's CDS
     downloads) — `_extract_or_use_directly()` now detects and handles both.
  2. The time dimension is named **`valid_time`, not `time`** — both
     `_find_discharge_var()`'s dimension check and the rename step now handle
     this alongside the existing `latitude`/`longitude` → `lat`/`lon` rename.
  The retrieved discharge grid is sparse (NaN off the river network, finite
  values of a few m³/s to tens of m³/s on it) — exactly the pattern the
  river-corridor design in §3 exists to handle correctly.

Remaining open items:

1. **Corridor width default.** Still a flat 5 km default (or
   Strahler-order-scaled) — a real methodological choice that needs
   validation against observed WASH impacts, not just assumed correct, per
   the note's own risk flag.
2. **Pilot countries.** The note suggests SOM/KEN/NER/SSD/AFG; this repo's
   actual operative batch list (`data/batch_tasks.csv`) is 12 countries
   (SDN, YEM, LBN, CAF, MLI, AFG, COD, HTI, MMR, MOZ, SOM, BFA) — using that
   list as "the 12 WIA priority countries" for prototype testing unless you
   mean a different set.
3. **Baseline download cost.** A full 1991–2020 baseline is 360 monthly
   requests per country (confirmed: a single month for one country takes
   roughly a minute end-to-end against the live API); this is a real
   operational cost, not just a design footnote — consider a shorter baseline
   (`--baseline-start-year`) for faster prototype iteration before committing
   to the full WMO normal for production countries.

## 8. What this session builds now

This pass builds the full pipeline plumbing, registry wiring, docs, and unit
tests; validates it structurally (dry-run, config validation, synthetic-data
unit tests) against all 12 countries in `data/batch_tasks.csv`; and validates
the acquisition path for real against the live EWDS API and real Somalia
WorldPop/HydroRIVERS data (geography prep, bbox-filtered river load, corridor
computation, one real month of GloFAS download and processing). Not run in
this session: a full 12-month, 6-variant, admin-aggregated production run for
any country — the baseline-download cost in item 3 above makes that a
multi-hour operation better run deliberately than as part of this build pass.
