# Extreme cold indicator (UTCI)

Cold mirrors the extreme heat indicator ([heat-utci.md](heat-utci.md)). It runs
through the same module (`hazards/utci.py`) with `extreme="cold"`, registered as
hazard `cold`, pipeline `extreme_cold_utci`, method version 0.1.0.

## Definition

The Copernicus `derived-utci-historical` daily statistics carry both
`utci_daily_max` and `utci_daily_min`. Heat uses the maximum. Cold uses the
**daily minimum UTCI** and tests whether a pixel is **strictly below** a
threshold for k consecutive days (default k = 3). A pixel is affected when at
least one such run occurs in the analysis window. Affected population is
WorldPop 100 m on the resulting binary mask.

Default thresholds are the UTCI cold-stress categories: -13 °C (strong),
-27 °C (very strong) and -40 °C (extreme). They are the standard categories
(Bröde et al. 2012) but were not re-checked against the ISB reference in the
build session; confirm before quoting them.

## Run

```bash
wia-hazards run-utci --iso3 AFG --as-of-date 2026-06-30 --extreme cold \
  --default-reporting-threshold-c=-27
```

- `--abs-threshold-c=-20` (repeat) overrides the thresholds. Use `=` for negatives.
- Cold with the heat default thresholds is rejected; the cold defaults apply automatically.
- `--default-reporting-threshold-c` sets the headline columns (`pct_affected`) and maps.
  It defaults to the first threshold (-13 °C), which saturates in AFG. Set it per country.
- The CDS cache is shared with heat (`outputs/_cache/heat/<ISO3>/cds_raw`): the request is
  identical, so running cold after heat needs no new download.
- Post-run checks: `python scripts/utci_postrun.py --run-dir outputs/<ISO3>/<window>/cold`.

## Batch

`utci_cold` is a default `batch-run` pipeline (`PIPELINES` in `batch/execute.py`), run after `utci`:

```bash
wia-hazards batch-run --readiness-report ... --preflight-report ... --pipeline utci_cold
```

- It shares the UTCI readiness and preflight checks (`can_run_utci`, `utci_preflight_status`);
  no separate preflight is needed because the CDS dataset, area and inputs are the same.
- The default command adds `--extreme cold` to the heat command (cold thresholds -13, -27, -40 °C).
  Override it with `--utci-cold-cmd-template`, for example to add `--abs-threshold-c=-5` or set
  `--default-reporting-threshold-c`.
- The batch headline (`pct_affected`) is the first threshold, -13 °C, which saturates in the pilot
  countries. The table keeps every threshold; select the band per country downstream.
- The hand-written country batch scripts (`scripts/run_*_batch.sh`) are unchanged and do not run cold.

## Outputs

Same contract as heat, under `outputs/<ISO3>/<window>/cold/`:

- `tables/<ISO3>_admin2_<vintage>_extreme_cold_<date>.csv`: `pop_total`,
  `pop_exposed_cold_m27c`, `pct_exposed_cold_m27c` per threshold (`m` = minus), plus the
  standard summary columns;
- binary masks, affected-population rasters, QC JSON, parity report, two maps.

## Implementation choices

- Comparison is strict (`<`), on the daily minimum. Missing values are never cold.
- Kelvin values are converted to Celsius when detected.
- Parity monotonicity is checked mild to severe (-13, -27, -40: exposed population must not increase).
- The 12-month window ending 30 June holds one northern-hemisphere winter. Southern-hemisphere
  countries need a different `--as-of-date` so their winter (Jun-Aug) is not split.

## AFG pilot (window 2025-07-01 to 2026-06-30, k = 3, 401 districts, 43.25 m people)

| Threshold | Pop-weighted % exposed | Districts >= 99% | Districts <= 1% |
|---|---|---|---|
| -13 °C | 94.8 | 360 | 8 |
| -27 °C | 42.7 | 132 | 163 |
| -40 °C | 2.2 | 2 | 376 |

-13 °C saturates and -40 °C is almost empty, so -27 °C is the discriminating band for AFG.
This is one winter and one country; the band should be chosen per country from the same table.
Post-run checks: 0 failures, 7 warnings (the same 7 as the heat run: WorldPop coverage 99.99% and
sub-0.01% rounding differences).

## Validation against REACH (AFG)

`scripts/validate_cold_vs_reach.py` joins the REACH district workbook (401 districts, 400 matched
directly; REACH AF2110 is our AF2008) to the AFG cold table. REACH gives, per month, the number of
the 27 winters (2000-2026) at each SMI severity; we use the December-February mean of winters at
severity 3-4 (and 4 alone).

Spearman rank correlation across 400 districts with our exposure (2025-26 winter):

| Our threshold | REACH sev 3-4 (DJF) | REACH sev 4 (DJF) | REACH sev 3-4 (any month) |
|---|---|---|---|
| -13 °C | 0.20 | 0.20 | 0.27 |
| -27 °C | 0.17 | 0.30 | 0.30 |
| -40 °C | 0.22 | 0.32 | 0.24 |

The correlation is weak and positive. This is not a pass or a fail, because the two measure different
things:

- REACH severity is mostly an anomaly rule (2 or 3 SD below the district's own climate). Its
  frequency is close to uniform across districts (mean 1.6 winters of 27 in DJF; maximum 5), so it
  does not follow altitude. The UTCI layer is absolute and follows altitude and exposure to wind.
- Ours is one winter; REACH is a 27-winter frequency. REACH publishes counts, not per-winter results.
- REACH uses ERA5 2 m minimum temperature; UTCI adds wind, humidity and radiation.

REACH therefore cannot validate an absolute-threshold layer. A like-for-like test would apply the SMI
rule to ERA5 for the same winters (option B in the design) and compare that with the REACH counts.

## Transfer tests (window 2025-07-01 to 2026-06-30, k = 3, admin2)

| Country | Units | Threshold | Pop-weighted % exposed | Units >= 99% | Units <= 1% |
|---|---|---|---|---|---|
| UKR | 139 raions | -5 °C | 100.0 | 139 | 0 |
| UKR | | -13 °C | 100.0 | 139 | 0 |
| UKR | | -27 °C | 90.0 | 109 | 6 |
| UKR | | -40 °C | 3.2 | 2 | 126 |
| MNG | 339 soums | -5 °C | 100.0 | 339 | 0 |
| MNG | | -13 °C | 100.0 | 339 | 0 |
| MNG | | -27 °C | 100.0 | 339 | 0 |
| MNG | | -40 °C | 89.0 | 250 | 9 |

Both runs pass the post-run checks (0 failures; warnings are table-versus-raster differences under
0.11%). The AFG bands do not transfer: UKR is nearly saturated at -27 °C (spread only between about -27 and
-40 °C), and MNG needs -40 °C. UTCI includes wind chill, so the values sit well below air temperature.
Thresholds must be set per country from the diagnostic table, in line with the WIA choice of
per-country thresholds. Suggested headline bands: AFG -27 °C, UKR -27 °C (weak spread; -40 °C is
nearly empty), MNG -40 °C. UKR and MNG each have only one band that separates units.

## Not yet done

- Like-for-like validation (SMI rule on ERA5, or UTCI anomalies) against the REACH counts.
- Zero-by-rule check for SOM, CAF and COD; `scripts/country_hazard_coverage_check.py` integration.
- Long-run exposure layer (HE-15 equivalent, CCRI/GEE) and snow-depth isolation.
- Sidecars and the WIA loader change.
