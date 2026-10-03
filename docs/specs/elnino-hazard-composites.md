# Reference pipeline specification: El Niño hazard composites and pre-mask severity rasters

| | |
|---|---|
| Status | Approved for build, 3 October 2026 (James Brown) |
| Spec version | 0.2.0 (0.1.0 revised after a code review against commit `7aa5e84`) |
| Repository | `JamesElliot/wia-hazard-impact-pipelines` |
| Method note | "El Niño hazard-impact evaluation: method proposal for WIA" (Claude Docs, 3 Oct 2026) |
| Country config | [`configs/elnino_seasons.yml`](../../configs/elnino_seasons.yml) |
| Build order | Contract change → ERA5 products (SPEI/SPI, UTCI) → El Niño module → pilot → GFM flood → roll-out |

## 1. Purpose

Estimate, per admin-2 unit, how much past El Niño events changed the share of people affected by drought, extreme heat, wet extremes and flooding in the eight priority A WIA countries. Also produce presentation-ready pixel-level hazard severity maps. The work re-uses the existing hazard pipelines over many historical season windows, then compares El Niño seasons with neutral seasons.

The output is a historical conditional estimate. It is not a forecast and it does not change any WIA indicator definition.

## 2. Scope

### In scope

| Item | Priority | Notes |
|---|---|---|
| Pre-mask hazard severity rasters, added to the output contract | P1 | SPEI/SPI and UTCI first; GFM flood after the ERA5 pilot |
| ERA5-Drought extensions: SPI and SPEI, accumulation 1/3/6/12, season-end evaluation, wet tail | P1 | New hazard IDs `drought_seasonal`, `wet_extreme`, with a run `variant` |
| UTCI extensions: heat-days and longest-run severity layers | P1 | Additive outputs; reporting rule unchanged |
| El Niño module: indices, catalogue, season instances, runner, panel builder | P1 | New package `wia_pipelines.elnino` |
| Statistics (method note step 3a): composite difference, permutation test with FDR, risk ratio, analogue count, dose response | P1 | Primary output |
| Pixel-level El Niño composite and anomaly rasters and maps | P1 | Built from the severity rasters |
| GFM flood: seasonal windows, valid-observation raster, flood frequency | P2 | After the ERA5 pilot is signed off |
| Targeting overlay (method note step 3c) | P3 | Secondary output; needs a baseline WIA score file per country |

### Out of scope (do not build)

- Hydrological drought (`hydrodrought`, GloFAS SRI). It is held until that pipeline is validated. Do not run it, extend it or add it to any El Niño config.
- Scenario WIA runs (method note step 3b). Parked. Do not substitute HI values or call the WIA engine.
- Cyclone, cholera, violence, earthquake, cold.
- Any change to the default reporting rule, thresholds, method version or **admin-table columns** of an existing hazard. Existing `drought`, `heat` and `flood` admin tables must reproduce exactly (parity tests). New information for existing hazards goes into new files, never new columns.

## 3. Countries, seasons and record

Priority A countries (confirmed 3 Oct 2026): **SOM, KEN, SSD, MOZ, MDG, HTI, AFG, SDN**. Pilot: **SOM** and **MOZ**, plus the **SDN** `rains_jas` season for an out-of-sample check on July–September 2026.

Season windows, accumulations, ENSO reference seasons, expected direction and thresholds are defined only in `configs/elnino_seasons.yml`. Code must not hard-code them. Drought and wet windows using `evaluation: end` must be 1, 3 or 6 months long, because those are the accumulations ERA5-Drought distributes that fit a season (1, 3, 6, 12, 24, 36, 48).

Record: **1981–2025** by default (`record.start_year`), with `record.start_year: 1951` supported. Pre-1979 instances carry `pre_satellite = true` and are excluded from headline statistics.

### 3.1 Known bug to fix first: window start dates

`config._subtract_months` gives a wrong start date when `as_of_date` is a month end and the start month is longer than the end month. Examples: `2016-04-30` m6 gives `2015-10-31` instead of `2015-11-01`; `2016-02-29` m5 gives `2015-09-30` instead of `2015-10-01`. ERA5-Drought month selection uses `core.cds.months_for_last_n` and is unaffected. The UTCI daily slice and the GFM STAC query use `window_start`, so they pick up extra days.

Fix it so that a month-end `as_of_date` yields the first day of the start month. Add tests showing that the standard windows (`YYYY-12-31` m12, `YYYY-06-30` m12) and their run IDs are unchanged. List any existing outputs under `outputs/` whose run ID would change, and report them; do not rename them.

## 4. Contract change: pre-mask hazard severity rasters

Add a section "Hazard severity rasters" to `docs/output-contract.md` with the text in 4.1–4.5, and bump `schema_version` to `1.3.0` (update `tests/test_data_sources.py`, which asserts 1.2.0).

### 4.1 Definition

A severity raster is the continuous or count hazard field for the run window **before** population masking, thresholding to a binary mask, resampling to the WorldPop grid, or admin aggregation. It shows where and how strongly the hazard occurred, independent of where people live.

### 4.2 Location and naming

```text
rasters/severity/<ISO3>_<hazard>[__<variant>]_<layer>_<YYYY-MM>_<YYYY-MM>.tif
maps/severity/<ISO3>_<hazard>[__<variant>]_<layer>_<YYYY-MM>_<YYYY-MM>.png
```

The two month labels are the first and last month of the window, so file names do not depend on `window_start` day arithmetic.

### 4.3 Raster requirements

- Grid: the hazard's native grid (ERA5 0.25°; for GFM, the WorldPop-resolution box the flood pipeline already accumulates on). No resampling. Clip ERA5 layers to the country with `all_touched=True`.
- Format: Cloud-Optimised GeoTIFF via rasterio's GDAL `COG` driver (no new dependency), deflate compression. A test confirms the file opens with internal overviews and tiling.
- dtype and nodata: float32 with nodata −9999 for continuous layers; uint16 with nodata 65535 for counts. Nodata means "outside the country or no valid observation". Zero is a real value for counts.
- GDAL metadata tags on every file: `layer`, `units`, `description`, `hazard`, `variant`, `first_month`, `last_month`, `threshold` (where the layer depends on one), `source_dataset`, `method_version`.
- Register each file in `run_metadata.json` `artifacts` with `kind: "severity_raster"` and extra fields `layer`, `units`, `min`, `max`; PNGs use `kind: "severity_map"`. Artifact items are an open object in the schema, so do not add a kind enum (it would invalidate older runs). Extend `io_paths.append_artifact` to accept extra keyword fields. Document both kinds in the contract.

### 4.4 Layers by hazard

| Hazard | Layer | dtype | Units | Definition |
|---|---|---|---|---|
| `drought` (existing SPEI12 run) | `spei12_min` | float32 | index | Minimum SPEI12 over window months |
| `drought` | `months_le_<thr>` | uint16 | months | Months with SPEI12 ≤ threshold, one layer per configured threshold |
| `drought_seasonal`, `wet_extreme`, `evaluation: end` | `<index><n>_end` | float32 | index | SPEI-n or SPI-n at the window's last month |
| `drought_seasonal`, `evaluation: any` | `<index><n>_min`, `months_le_<thr>` | float32, uint16 | index, months | Minimum over window months; months at or below threshold |
| `wet_extreme`, `evaluation: any` | `<index><n>_max`, `months_ge_<thr>` | float32, uint16 | index, months | Maximum over window months; months at or above threshold |
| `heat` | `utci_max_c` | float32 | °C | Maximum of daily-maximum UTCI over the window |
| `heat` | `days_gt_<thr>` | uint16 | days | Days with daily-maximum UTCI above threshold, per configured threshold |
| `heat` | `maxrun_gt_<thr>` | uint16 | days | Longest consecutive run above threshold, per configured threshold |
| `flood` (P2) | `flood_days` | uint16 | days | **Copy and re-encode** the existing flood-days raster (never move it: the pipeline's reuse check depends on its path). Pixels with `valid_obs_days == 0` become nodata |
| `flood` (P2) | `valid_obs_days` | uint16 | days | Days on which the pixel had a valid GFM observation (section 7) |
| `flood` (P2) | `flood_frequency` | float32 | fraction | `flood_days / valid_obs_days`; nodata where `valid_obs_days == 0` |

Threshold tokens follow the existing style: `m1p5` for −1.5, `p1p5` for +1.5, `38c` for 38°C.

### 4.5 Presentation maps

One PNG per severity layer, made for slides:

- 1920 × 1080 px, white background. Inter font from the directory in config `fonts.inter_dir`; fall back to Arial with a logged warning.
- **Fixed, not data-driven, colour limits**, so maps compare across years and countries:
  - SPEI/SPI: −3 to +3, diverging (dry brown to wet blue, white at 0).
  - UTCI maximum: 26–50°C.
  - Day counts: classes 0, 1–2, 3–5, 6–15, 16–30, > 30.
  - Month counts: one class per value from 0 to the window length.
  - Flood frequency: 0–1.
- Single-hue impact ramps follow the WIA brand book: Hazard Impact `#F76469` to white. Where the visualisation standard in the `wia-workflow-standards` repo says otherwise, it wins.
- Admin-1 boundaries thin grey, country outline black.
- Title = hazard and layer in plain words. Subtitle = months and threshold. Footer = data credit from the run's `data_sources` attribution.
- No basemap tiles and no network calls during plotting.

Implement once in `core/severity.py` (array → COG + tags + artifact) and `core/severity_maps.py` (COG → PNG), and call them from every pipeline.

## 5. ERA5 pipeline extensions

### 5.1 Shared CDS cache and year-batched prefetch

The current SPEI cache key includes the window end month (`spei.py`: `{iso3}_spei12_{aoi_hash}_{end_yyyymm}`), so the same month is downloaded again for every window. Replace it with a window-independent cache keyed on `(dataset, variable, accumulation, product tier, aoi_hash, year, month)` under `outputs/_cache/_shared/era5_drought/<ISO3>/`. The UTCI cache (`_cache/heat/<ISO3>/cds_raw`, month-keyed) stays as it is. The old `_cache/water_scarcity_spei12` tree is left in place and documented as superseded.

Add `wia-hazards prefetch-era5 --iso3 SOM --dataset drought|utci --years 1981-2025 [--index spei,spi] [--accumulation 1,3,6,12] [--admin-path …]`:

- It resolves the admin path the same way the run commands do, so `aoi_hash` matches.
- It requests one year (all 12 months) per CDS call, and falls back to per-month calls if CDS rejects the size.
- Pipelines read from the cache and only call CDS for what is missing.
- Retrieval dates are recorded as the repo already does (`.retrieved.json`).
- The consolidated → intermediate fallback stays. The intermediate tier is needed for the 2026 out-of-sample check.

### 5.2 New hazard IDs and the run variant

Register in `SUPPORTED_HAZARDS`, `HAZARD_METHODS` and the schema's hazard list:

| Hazard ID | Pipeline ID | Method version | Population rule |
|---|---|---|---|
| `drought_seasonal` | `water_deficit_era5_seasonal` | 0.1.0 | WorldPop cells where SPEI-n (or SPI-n) is at or below the threshold at the window's last month (`end`) or in any window month (`any`) |
| `wet_extreme` | `wet_extreme_era5_spi` | 0.1.0 | WorldPop cells where SPI-n (or SPEI-n) is at or above the threshold, same evaluation modes |

Add an optional `variant: str | None` to `RunConfig`:

- Token = `<index><accumulation><evaluation>`, e.g. `spei3end`, `spi1any`, `spi6end`. It is required for the two new hazards and must be `None` for every existing hazard.
- `run_id` gets `__<variant>` appended when set. The run folder becomes `outputs/<ISO3>/<WINDOW>/<hazard>__<variant>/`. Without a variant, both are unchanged.
- Add `run_config.variant` (optional) to the schema. Include the variant in any resume or step key, so `spi3end` and `spi1any` over the same window are separate runs.

Refactor `spei.py` into a parameterised core: `index` (spei, spi), `accumulation_months`, `direction` (dry, wet), `evaluation` (end, any), `thresholds`. The existing `drought` hazard calls the core with its current fixed parameters, and its admin table must be identical (parity). CLI: `run-drought-seasonal` and `run-wet-extreme`, taking `--index --accumulation-months --evaluation` plus the usual run arguments.

Defaults: dry thresholds −1.0, −1.5, −2.0 (reporting −1.5); wet thresholds +1.0, +1.5, +2.0 (reporting +1.5).

Extend the ERA5-Drought `data_sources` entry with the index and accumulation actually requested.

### 5.3 UTCI

Add the three severity layers in 4.4 to `utci.py`. They come from the daily stack the pipeline already holds, so no extra download is needed. The binary mask, thresholds and admin table do not change.

The heat headline threshold per country is set explicitly in the YAML (`heat_headline_c`). All three thresholds (32, 38, 46°C) are always computed.

### 5.4 Severity summaries (sidecar table)

For every hazard, write a sidecar table `tables/<ISO3>_<admin>_<vintage>_<hazard>[__<variant>]_severity_<YYYY-MM>_<YYYY-MM>.csv`. Columns: `admin_pcode`, then `sev_popw_mean_<layer>` for each severity layer. Each value is the population-weighted mean over valid WorldPop cells, using nearest resampling of the severity layer onto the WorldPop grid for this calculation only. Register it as artifact kind `severity_summary_table`. The main admin table is not touched.

## 6. El Niño module (`src/wia_pipelines/elnino/`)

### 6.1 Climate indices (`indices.py`)

| Index | Source | Use |
|---|---|---|
| ONI v5 | `https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt` | Catalogue and classification |
| Dipole Mode Index (IOD) | NOAA PSL HadISST DMI series (confirm URL) | Covariate for SOM, KEN, SSD |
| Tropical North Atlantic index | NOAA PSL TNA series (confirm URL) | Covariate for HTI |

- Download into `data/climate_indices/` with a `.retrieved.json` record, and list each in the analysis metadata `data_sources`. Analyses use the pinned copy. Re-download only on `--refresh-indices`.
- ONI season labels use the year of the **central** month (`DJF 1950` = Dec 1949–Feb 1950; `NDJ 2015` = Nov 2015–Jan 2016). Unit-test this.
- The out-of-sample 2026 check needs ONI for JAS 2026. CPC normally publishes it in early October. If it is not in the file yet, classify 2026 as El Niño provisionally (CPC El Niño Advisory; JJA 2026 = +1.80), flag the instance `provisional_enso`, and say so in the report.

### 6.2 Event catalogue (`catalogue.py`)

- Episode: at least 5 consecutive overlapping seasons with ONI ≥ +0.5 (La Niña: ≤ −0.5).
- Class by episode peak: weak 0.5–0.99, moderate 1.0–1.49, strong 1.5–1.99, very strong ≥ 2.0.
- **ENSO year Y0** of an episode = the year of its peak season's central month if that month is July–December, otherwise that year minus 1.
- **Episode ID** = `f"{Y0}-{(Y0 + 1) % 100:02d}"`. For example, the SON 2014–AMJ 2016 episode peaks NDJ 2015 and is `2015-16`; the 1982–83 episode peaks DJF 1983 and is `1982-83`.
- Regression test on the pinned ONI file: 22 El Niño episodes from 1951; 14 moderate or stronger; IDs and peaks `1982-83` 2.14, `1997-98` 2.37, `2015-16` 2.59, `2023-24` 1.99 (class strong).
- Output: `outputs/_elnino/catalogue/oni_episodes.csv` (episode ID, phase, onset season, end season, peak, peak season, class, Y0).

### 6.3 Season instances and classification (`seasons.py`)

For each country × season × run in the config and each year t in the record, build one instance: `as_of_date` (last day of `end_month` in year t), `lookback_months`, hazard, variant and reference season. A run entry may override the season's `end_month` and `length_months` (used for SPI-6 basin windows); the reference season stays the season's.

Validate the config: every `enso_ref.season` must have its central month in July–December (JAS, ASO, SON, OND, NDJ). The reference central-month year is r = t + `central_year_offset`.

Classification (one label per instance):

| Label | Rule | Used in |
|---|---|---|
| `elnino` | r = Y0 of an El Niño episode **and** ONI at the reference season ≥ +0.5. Carries `episode_id`, `episode_class`, `is_core_analogue` | Composites (moderate-plus only), dose response |
| `elnino_weak` | As above but episode class weak | Dose response only |
| `elnino_secondary` | Reference season inside an El Niño episode but r ≠ Y0 (e.g. OND 2014 in the 2015-16 episode) | Dose response only |
| `lanina` | Reference season inside a La Niña episode | Dose response only |
| `neutral` | Reference season in no episode and \|ONI\| < 0.5 | Baselines, tests |
| `excluded_other` | Anything else (e.g. \|ONI\| ≥ 0.5 outside an episode) | Nothing; counted in the report |

This gives at most one El Niño instance per episode per season, so the core analogue count runs from 0 to 4.

**Dedupe runs.** Season definitions that share hazard, variant and window (for example SSD `flood_jul_dec_y0` and `flood_jul_dec_y1`, or HTI `heat_jas_y0` and `heat_jas_y1`) are run once. Classification is applied per season definition in the panel. With the default config, that is 35 unique ERA5 run definitions (about 1,575 runs over 1981–2025) and 8 unique flood definitions (88 runs over 2015–2025). Report the CDS load as months × products, not runs.

### 6.4 Runner (`runner.py`)

- Use a lightweight runner in this module that calls the Python run functions directly (`run_spei_pipeline` core, `run_utci_pipeline`, `run_flood_pipeline`), with its own resume and retry. Do not route through `batch-run`: it expects readiness and preflight frames and pipeline aliases, and its command templates do not pass `--worldpop-path`.
- **Population fixed**: always pass the country's WorldPop **2025** raster explicitly, and record its path and checksum in the analysis metadata.
- **Boundaries fixed**: the country's current COD spine, as resolved by `core.assets`.
- Resume: a run whose `run_metadata.json` has `status == SUCCESS` is skipped (`skip_if_complete`).
- Log CDS requests, bytes and elapsed time per country.
- CLI: `wia-hazards elnino-run --iso3 SOM [--seasons deyr_ond,...] [--hazards drought_seasonal,wet_extreme,heat] [--years 1981-2025] [--dry-run]`. `--dry-run` prints the deduplicated run list and the CDS month × product count, with no network calls.

### 6.5 Panel builder (`panel.py`)

Stack the admin tables and severity sidecars of all instances into one long table per country, season and hazard-variant:

```text
outputs/<ISO3>/_elnino/<analysis_tag>/panel/<ISO3>_elnino_panel_<season_id>_<hazard>[__<variant>].csv
```

Columns: `iso3, admin_pcode, season_id, hazard, variant, year, first_month, last_month, enso_label, episode_id, episode_class, is_core_analogue, oni_ref, dmi_ref, tna_ref, pre_satellite, provisional_enso, population_total, population_affected, pct_affected, pct_affected_<thr>…, sev_popw_mean_<layer>…, hazard_data_coverage, run_id`.

- Map hazard-specific threshold columns (e.g. `pct_affected_rel_spei_le_m1p5`, `pct_exposed_abs_38c`) to `pct_affected_<thr token>` through an explicit, tested mapping per hazard.
- Take `variant` and `season_id` from the runner's manifest, not from the tables.
- `analysis_tag` = `elnino_<YYYY-MM-DD>_v<n>`.

### 6.6 Statistics (`stats.py`): method note step 3a, primary output

Unit of analysis: country × season × hazard-variant × metric × admin unit. Metrics are `pct_affected` at the reporting threshold and each `sev_popw_mean_<layer>`. Each run entry in the config has `expected: increase | decrease | either` (default `increase`).

Use only numpy, scipy and pandas (no new dependencies).

1. **Sample.** The test sample is `elnino` (moderate-plus) and `neutral` instances, excluding `pre_satellite` and `excluded_other`.
2. **Detrending.** Fit a linear trend in year on the neutral instances per unit. Let x′ = x minus that trend, for all instances. This removes the warming trend from the comparison.
3. **Effect size (descriptive).** Composite difference = mean over El Niño instances of (x − local neutral mean), where the local neutral mean uses neutral instances in [t − 10, t + 10]. If fewer than `min_neutral_seasons` are found, widen the window symmetrically and record the window used. Report it in percentage points and in people (difference × 2025 `population_total`), for all moderate-plus events and for core analogues separately.
4. **Permutation test.** Statistic = mean(x′ | El Niño) − mean(x′ | neutral). Shuffle labels among the test sample, 10,000 times, with a fixed seed. Use a two-sided p for `either`, and one-sided in the expected direction otherwise.
5. **FDR.** Benjamini–Hochberg across admin units within each country × season × hazard-variant × metric family. Report `p` and `q`.
6. **Exceedance.** Threshold = 80th percentile of neutral x′ (`numpy.quantile`, linear method) for `increase`, or the 20th percentile for `decrease`. Exceedance is strictly beyond the threshold.
   - If more than 50% of neutral raw values are 0 (zero-inflated `pct_affected`), use "raw value > 0" as the exceedance event instead, and flag `zero_inflated`.
7. **Risk ratio.** RR = (a / n₁) / (c / n₀), where a of n₁ El Niño and c of n₀ neutral instances exceed. Always report a, n₁, c and n₀. If a or c is 0, use the Haldane form ((a + 0.5) / (n₁ + 1)) / ((c + 0.5) / (n₀ + 1)) and flag `haldane`.
8. **Analogue count.** The number of core analogues (0–4) exceeding the threshold in the expected direction.
9. **Dose response.** OLS of x on `oni_ref` + year (+ `dmi_ref` or `tna_ref` where configured), with HC3 standard errors implemented in numpy. The sample is all labelled instances except `excluded_other` and `pre_satellite`. Report the slope per °C and the predicted change at `forecast_oni_ref` (config; +2.5). Flag `extrapolation = true` when that value exceeds the sample's ONI maximum.
10. **Leave-one-event-out.** Recompute RR dropping each core analogue in turn. Flag `unstable = true` if RR crosses 1.
11. **Consistency label.** `consistent` if analogue count ≥ 3 and q ≤ 0.10; `indicative` if one of the two holds; otherwise `uncertain`. For `either`, use the direction of the composite difference.

Output: `stats/<ISO3>_elnino_profile_<season_id>_<hazard>[__<variant>].csv`, one row per admin unit and metric. Also write a country summary CSV with population-weighted national figures and the count of units per consistency label.

### 6.7 Pixel-level composites (`composites.py`)

From the severity rasters of all instances, on the native grid, for each layer:

- `elnino_mean_<layer>`, `neutral_mean_<layer>`, and `anomaly_<layer>` (mean over El Niño instances of the instance value minus its local neutral mean);
- `analogue_count_<layer>`: the number of core analogues beyond the per-pixel neutral threshold, using the 6.6 step 6 rule without the zero-inflation switch;
- `anomaly_<layer>_<episode_id>` for each core analogue (for slides: "what 2015-16 looked like").

Write to `outputs/<ISO3>/_elnino/<analysis_tag>/rasters/` using the 4.3 rules, and PNGs to `maps/` using the 4.5 rules. Anomaly maps use a symmetric diverging scale with fixed limits from config `anomaly_map_limits`.

### 6.8 Targeting overlay (`overlay.py`): step 3c, secondary, P3

- Input: `wia_baseline_csv` per country in config, with `admin_pcode` and `wia_score_excl_hazard`. If it is missing, skip with a logged message. Do not compute WIA scores.
- High uplift = RR > `risk_ratio_high` (1.5) with q ≤ 0.10. High insecurity = top tercile of the baseline score.
- Output: a CSV with the four classes and a 2×2 scatter PNG. Quadrants: Act before the season, Chronic need, Hazard watch, Routine monitoring.

### 6.9 Analysis metadata

Write `outputs/<ISO3>/_elnino/<analysis_tag>/elnino_metadata.json`, validated against a new `schemas/elnino_metadata.schema.json`. It records:

- spec version, config SHA-256, git commit, record years;
- WorldPop path and checksum, admin source, and index retrieval records;
- the run IDs used;
- every statistic parameter, including the seed.

## 7. GFM flood (P2, after ERA5 pilot sign-off)

- **Seasonal windows.** Generalise `flood_bulk` to season windows from the config: `calendar_year_windows`, `_run_paths` (which hard-codes m12 and 31 December) and `completed_flood_year`. CLI: `run-flood-bulk --season-config configs/elnino_seasons.yml --iso3 SOM`. Windows run 2015–2025; seasons that start before 2015 (e.g. MOZ Dec 2014–Mar 2015) are skipped and listed.
- **Valid observations.** In the daily streaming loop of `flood.py`, accumulate `valid_obs_days` alongside `flood_days`.
  - Pass an explicit `nodata` (and fill value) to `stac_load` so that pixels no item covers are not read as 0 and counted as observed. Test this with a synthetic item that covers half the grid.
  - Check the GFM product user manual for whether the exclusion mask must also be applied, and record the decision in `docs/indicators/flood.md`.
- **Reused rasters.** Runs that reuse an existing `flood_days` raster have no `valid_obs_days`. Mark them `valid_obs_unavailable`, keep their `flood_days` as is, and do not compute `flood_frequency`.
- **El Niño comparison.** Rank the El Niño instances among the seasons for each unit and report percentile ranks. No permutation test, because n is too small.
- **Coverage.** Flag seasons whose median `valid_obs_days` is below config `flood.min_median_valid_obs_days` as `low_coverage`. Sentinel-1B was lost in December 2021 and Sentinel-1C entered service in 2025, so the 2022–2024 seasons have roughly half the revisit frequency.
- **Downloads.** They are heavy. Run one country at a time and log STAC item counts and elapsed time per season.

## 8. Testing and acceptance

Add `addopts = "-m 'not integration'"` to `[tool.pytest.ini_options]` in `pyproject.toml`. The `integration` marker is declared but not yet applied anywhere. Mark every network- or CDS-dependent test with it.

| Area | Test |
|---|---|
| Parity | Existing `drought`, `heat` and `flood` admin tables for synthetic fixtures are identical before and after the refactor (added before any refactor) |
| Window fix | Month-end windows give the first day of the start month; standard Dec-31/Jun-30 m12 run IDs unchanged |
| Variant | `RunConfig` with and without a variant; run ID and folder; two variants over one window do not collide on resume |
| Severity rasters | Synthetic SPEI and UTCI stacks give the expected min/max, counts and longest run; COG structure (tiling and overviews); tags present; nodata semantics |
| Contract | Metadata with severity artifacts validates against schema 1.3.0; a 1.2.0 metadata fixture with no variant still validates |
| ONI | Central-month year parsing; episode count, IDs and peaks on the pinned ONI file (6.2) |
| Seasons | Classification of a hand-checked set: SOM `deyr_ond` 1997 = `elnino`, `1997-98`, very strong, core; SOM `deyr_ond` 2014 = `elnino_secondary`; MOZ `rains_ndjfma` 2016 = `elnino`, `2015-16`; SOM `deyr_ond` 2010 = `lanina`; config validation rejects a reference season centred January–June |
| Stats | A synthetic panel with a planted effect is detected; a null panel gives q > 0.10 for at least 90% of units; a trend-only panel is not flagged; results are reproducible with the seed |
| Flood | Uncovered pixels are not counted in `valid_obs_days` |
| CLI | `elnino-run --dry-run` makes no network calls and prints deduplicated counts |

Phase gates (stop and report to James at each):

1. **Contract and ERA5 extensions**: tests and parity green. One real SOM run each of `drought_seasonal__spei3end` and `wet_extreme__spi3end` for OND 2023, and `heat` for January–March 2024, with severity rasters and PNGs.
2. **Pilot**: SOM and MOZ ERA5 panels, 3a profiles and composite maps; the SDN `rains_jas` ERA5 panel; and the SDN July–September 2026 out-of-sample comparison.
3. **Flood**: SOM flood seasons 2015–2025 with `valid_obs_days`.
4. **Roll-out**: KEN, SSD, MDG, HTI, AFG, then the remaining SDN seasons.

## 9. Documentation to update

| File | Change |
|---|---|
| `docs/output-contract.md` | Section 4 of this spec; the `<hazard>__<variant>` folder rule; the severity sidecar table |
| `docs/methodology-alignment.md` | Method-registry rows for the new hazard IDs; method change history entries, including the window-start fix |
| `docs/indicators/drought-seasonal-era5.md`, `docs/indicators/wet-extreme-spi.md` | New |
| `docs/indicators/heat-utci.md`, `drought-spei.md`, `flood.md` | Severity layers |
| `docs/elnino.md` | How to run the module, outputs, how to read the statistics, and limitations: small samples, warming trend, IOD and Atlantic confounding, fixed population, ERA5 rainfall bias over Africa |
| `README.md` | New commands |

## 10. Open decisions (defaults used until James decides)

| Decision | Default in this spec |
|---|---|
| Record length | 1981–2025; 1951 start supported, pre-satellite instances excluded from headline statistics |
| Wet-tail accumulation | SPI-3 at season end (headline), SPI-1 any month in season, SPI-6 at season end for large basins (SOM, SSD) and the 6-month southern African and Afghan seasons |
| Heat headline threshold | HTI 38°C (current WIA run). Others are set to 38°C in the YAML and flagged `confirm`; check them against each country's current WIA run before gate 2 |
| New metrics in the WIA method generally | No: this analysis only |
| GFM exclusion-mask handling for `valid_obs_days` | To confirm in phase 3 |
| Forecast ONI used for the dose-response prediction | +2.5°C (NOAA CPC, 10 Sep 2026: 75% chance of exceeding +2.5°C in Oct–Dec) |
