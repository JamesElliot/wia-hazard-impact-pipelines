# Development Plan — Hazard Impact Pipeline: Population Exposed to Severe Hydrological Drought (GloFAS / SRI)

**Indicator:** Percentage of population residing within Admin2 units that experienced severe hydrological drought during the previous 12 months
**WIA dimension:** Current Hazard Impact
**Author:** Drafted for James Brown (WIA Coordinator, GWC)
**Date:** 24 July 2026
**Status:** Draft plan for review

---

## 1. Purpose and scope

This plan sets out how to build a reproducible, globally consistent pipeline that operationalises the methodology note for a hydrological-drought hazard-impact indicator. It scopes the data acquisition, hydrological processing, population overlay, admin aggregation, staging and workbook integration required, and identifies the design decisions and validation work needed before the indicator enters production.

The plan deliberately reuses the existing WIA hazard architecture rather than inventing a parallel one. The new indicator has the same shape as every other WIA hazard-impact indicator — *population × recent hazard footprint, aggregated to Admin2 as a percentage* — so the integration surface is already defined.

Out of scope: computing the WI score, redesigning the WIA Data file calculation engine, and selecting the single driving column in Excel (that remains a manual assembly step per current convention).

---

## 2. How this fits the existing WIA hazard architecture

The WIA hazard-impact stack has three layers. The new pipeline slots into each without structural change.

| Layer | What it does | Current analogue (SPEI drought, HI‑07) | New work required |
|---|---|---|---|
| **A. Global raster processing** | Turns a global hazard dataset into a per-Admin2 impact table `{ISO}_admin2_<hazard>_<window>.csv` under `…/global_datasets/…/m12_<hazard>/tables/` | Copernicus SPEI‑3 / ERA5 → `*_water_scarcity_spei3_*.csv` | **New processor**: GloFAS runoff → SRI → severe-drought footprint → WorldPop overlay → Admin2 table |
| **B. Staging** | Joins the impact table to the COD gazetteer, keeps all severity bands, writes `<table>.csv` + `.source.md` sidecar to `_wia_staged/model_ready/`, validates | `stage_country.py` stages `drought.csv` (HI‑07) via `source_registry.yaml` | **Registry entry** + optional discoverer pattern for the new table |
| **C. Workbook integration** | XML-surgery writes the `%`-impacted columns into the existing HI source sheet in the WIA Data file | `integrate_hazard_to_wia.py --drought …` → table `drought` | **Wire the new source** (reuse existing mechanism; decide HI slot — see §4) |

**Key implication:** the heavy lift is Layer A. Layers B and C already exist and only need configuration, because the output schema is fixed by the staging contract (§7). This keeps the new indicator consistent with floods (HI‑05/GFM), heat (HI‑08), conflict (HI‑11/ACLED) and displacement (HI‑09/IDMC).

---

## 3. Relationship to the current SPEI drought indicator (HI‑07)

The WIA already carries a drought hazard-impact indicator (HI‑07), currently derived from **SPEI‑3** (meteorological/agricultural drought) with three staged bands (`pct_affected_rel_spei_le_m1p0 / m1p5 / m2p0`). The methodology note argues that **hydrological** drought (river discharge, runoff, groundwater response) is a stronger conceptual link to WASH deterioration than precipitation deficits alone.

This creates a design choice that must be resolved before build (§4, Decision 1): the GloFAS indicator can **replace** HI‑07, **run in parallel** as an alternative driver, or occupy a **new HI slot**. The recommendation is to build it as a parallel `hydrodrought` table first, evaluate it against SPEI and observed impacts, then decide on promotion. This avoids disrupting countries already assembled on SPEI HI‑07.

---

## 4. Design decisions to resolve before build

| # | Decision | Options | Recommendation | Confidence |
|---|---|---|---|---|
| 1 | Indicator slot | (a) Replace HI‑07 SPEI; (b) parallel `hydrodrought` table, HI‑07 remains SPEI; (c) new HI code | **(b)** parallel table during validation; promote to HI‑07 driver only if it outperforms SPEI against observed impacts | Medium |
| 2 | Hydrological variable | SRI from modelled **runoff** (methodology's stated preference) vs **Standardised Streamflow Index (SSI)** from GloFAS **river discharge** (`dis24`, the natively distributed variable) | **Confirm runoff availability in the EWDS/CDS GloFAS catalogue.** If runoff is not distributed as an accessible variable, use SSI from river discharge and document the substitution. Both are standardised anomaly indices and interchangeable at the conceptual level | Medium — depends on catalogue |
| 3 | GloFAS product | GloFAS‑ERA5 **historical/reanalysis** (consistent 1979–present) vs **operational** (near-real-time, shorter record) | **Historical/reanalysis** for the baseline and the SRI reference distribution; use operational only if the 12-month window extends beyond the reanalysis latency | High |
| 4 | Accumulation period | Daily SRI (note's literal step) vs monthly accumulation SRI‑1/3/6/12 (standard drought-monitoring practice, WMO‑1173) | Compute **SRI on a monthly accumulation** (start with SRI‑3) rather than raw daily values; daily series are noisy and rarely used for drought classification. Expose accumulation as a parameter | High |
| 5 | Severity threshold | Moderate ≤ −1.0, Severe ≤ −1.5 (default), Extreme ≤ −2.0 | Stage **all three bands** (mirrors SPEI convention); default driver **≤ −1.5**; final threshold set by validation (§8) | High |
| 6 | Minimum duration | Any occurrence in 12 months vs ≥30 consecutive days | Stage **both** an "any-occurrence" and a "≥30-day persistence" footprint so sensitivity can be tested; default to persistence to reduce noise | Medium |
| 7 | Reference baseline | Period for fitting the SRI distribution (e.g. 1979–2020) | Fix a **stable, documented baseline** (recommend 1991–2020 WMO climate-normal, subject to record availability) and hold it constant across countries for comparability | Medium |
| 8 | GDO comparison | Adopt GloFAS now vs benchmark against Copernicus Global Drought Observatory (GDO) first | Run the **structured GDO vs GloFAS comparison** (methodology's own recommendation) on pilot countries in parallel with the build; do not block the pipeline on it | Medium |

Decisions 2, 4 and 7 depend on the exact GloFAS variable catalogue and record on the Copernicus Early Warning Data Store (EWDS); these should be confirmed against the live catalogue at the start of Phase 1 rather than assumed.

---

## 5. Data sources and access

| Dataset | Product / variable | Resolution | Coverage | Access | Licence |
|---|---|---|---|---|---|
| **GloFAS** | CEMS `cems-glofas-historical`; river discharge (`dis24`) and, if available, runoff | ~0.05° (~5 km) river grid; daily | Global, 1979–present | Copernicus EWDS / CDS API (`cdsapi`, API key) | Copernicus, free/open with attribution |
| **WorldPop** | Unconstrained/constrained population, most recent release matching WIA convention | ~100 m or ~1 km | Global | WorldPop REST / direct GeoTIFF | CC‑BY 4.0 |
| **COD‑AB** | Admin2 boundaries + p-codes; COD‑PS population | Vector | Per country | `hdx-cod-downloader` skill (already in project) | HDX / OCHA terms |

Notes:
- GloFAS is delivered via the **new Early Warning Data Store**; the older CDS endpoint is being migrated. Confirm the current endpoint, dataset name and API client version before scripting acquisition. *(Confidence: medium — verify against the live catalogue.)*
- Use the **same WorldPop release** already used by the flood (GFM) and heat pipelines so denominators are consistent across hazards. The COD gazetteer and `population_total` denominator are already standardised in the staging layer.

---

## 6. Pipeline stages (Layer A processor)

A standalone processor, mirroring the flood/heat GEE-style pattern but runnable locally (GloFAS is gridded NetCDF, not requiring Earth Engine). Proposed module home: `Data & Analysis/Hazard Code/` (alongside `integrate_hazard_to_wia.py`), with a country-agnostic core and a thin per-country runner.

| Stage | Task | Method / detail | Output |
|---|---|---|---|
| **0. Setup** | Environment & credentials | `cdsapi` (or EWDS client), `xarray`, `rioxarray`, `numpy`, `scipy`, `rasterio`, `geopandas`, `exactextract`/`rasterstats`. Store CDS/EWDS key in a config, never in code | Reproducible env; documented config |
| **1. Acquire** | Pull GloFAS runoff/discharge | Request the variable (Decision 2) for the **baseline period** (SRI fitting) and the **12-month window**, clipped to a country/regional bounding box to limit volume | NetCDF/GRIB time series per cell |
| **2. SRI computation** | Standardise the hydrological series | For each cell: accumulate over the chosen period (Decision 4); fit a distribution to the baseline (Decision 7) — gamma or empirical (Weibull plotting position), then transform to the standard normal to obtain SRI. Validate for zero-flow/intermittent rivers (gamma undefined at zero → use empirical or a mixed distribution) | Per-cell SRI time series |
| **3. Footprint** | Binary severe-drought raster | Flag a cell = 1 if SRI ≤ threshold (Decision 5) at any point in the 12 months, and (variant) if it persists ≥30 days (Decision 6). Produce one raster per band (≤−1.0, ≤−1.5, ≤−2.0) × per duration rule | Binary footprint rasters |
| **4. Population overlay** | Intersect with WorldPop | Resample/align footprint to WorldPop grid (or vice versa — resample coarser GloFAS footprint to population grid, nearest-neighbour, documenting the assumption that the river-cell classification applies to its contributing area). Compute affected population per cell = population × footprint | Affected-population raster per band |
| **5. Zonal aggregation** | Aggregate to Admin2 | Zonal sum of affected population and of total population per Admin2 p-code using the COD gazetteer; compute `pct_affected = 100 × pop_affected / pop_total` for each band and duration rule | `{ISO}_admin2_hydro_drought_<window>.csv` |
| **6. Stage & integrate** | Hand to Layers B and C | Register the table; run `stage_country.py`; write sidecar; validate join coverage; integrate into the WIA Data file via the existing XML-surgery script | Staged `hydrodrought.csv` + sidecar; populated WIA source sheet |

**Grid-mismatch caveat (important):** GloFAS is a **river-network** model — values are meaningful on the river grid, not uniformly across every land cell. A naïve raster overlay with WorldPop risks attributing river-cell drought to populations far from that reach. The processor must define, and document, how a river-cell SRI is generalised to the population it serves (e.g. catchment/contributing-area masking, or nearest-river assignment within a distance threshold). This is the single biggest methodological risk in Stage 4 and should be resolved explicitly, not by default resampling.

---

## 7. Output schema (staging contract)

The Layer A table and the staged `hydrodrought.csv` follow the existing rich-staging contract exactly, so Layers B and C need no schema changes. Columns mirror the current SPEI `drought.csv`:

```
adm0_pcode, adm0_name_en, adm1_pcode, adm1_name_en,
adm2_pcode, adm2_name_en, population_total,
pop_total,
pop_affected_rel_sri_le_m1p0,  pct_affected_rel_sri_le_m1p0,
pop_affected_rel_sri_le_m1p5,  pct_affected_rel_sri_le_m1p5,
pop_affected_rel_sri_le_m2p0,  pct_affected_rel_sri_le_m2p0
[+ *_p30 variants if the ≥30-day persistence footprint is staged]
```

Mandatory `.source.md` sidecar (per `wia-stage-inputs` contract): source organisation (Copernicus GloFAS / CEMS), admin level, reference window, SRI accumulation period and baseline, threshold definitions, units, SHA‑256, source path, join-coverage %, `wia_indicators`, `suggested_primary_column` (`pct_affected_rel_sri_le_m1p5`), and a `scale_note` recording that all bands are kept and the driver is chosen at assembly.

---

## 8. Code and configuration changes (concrete)

| File | Change |
|---|---|
| `Data & Analysis/Hazard Code/glofas_hydro_drought.py` *(new)* | The Layer A processor (Stages 1–5), country-agnostic core + CLI runner |
| `wia-stage-inputs/references/source_registry.yaml` | Add under `impact:` — `hydrodrought: {wia: HI-07 (candidate), level: adm2, pattern: "*admin2_hydro_drought*.csv", suggested_driver: pct_affected_rel_sri_le_m1p5}` |
| `wia-stage-inputs/scripts/stage_country.py` | Register discoverer/stager for the new pattern (reuses the generic rich-staging path) |
| `wia-stage-inputs/references/file_format.md` | Add `hydrodrought` to the canonical table-name list |
| `Data & Analysis/Hazard Code/integrate_hazard_to_wia.py` | Add `--hydrodrought` argument mapping to the target source table; decide whether it repoints HI‑07 or writes a parallel table (Decision 1) |
| `_templates/…` sidecar template | Extend if new provenance fields (SRI baseline, accumulation) are added |

All changes are additive; nothing removes the SPEI HI‑07 path during the validation phase.

---

## 9. Validation plan

Per the methodology note, validate the indicator (and tune threshold and duration) against independent evidence, on a representative pilot set. Suggested pilots spanning drought regimes and data availability: **SOM, KEN, NER, SSD** (and optionally **AFG**), all of which already have staged hazard data and, for several, MSNA and situation reports in-project.

| Reference | Use |
|---|---|
| WASH Cluster needs assessments; MSNAs | Compare affected-population % against reported water-access deterioration at Admin2 |
| National drought declarations; flash/appeal documents (several already in `0. Country Selection and Monitoring`) | Check the footprint flags declared drought areas |
| IPC analyses where water shortage is cited | Cross-check severity concordance |
| Reported borehole/spring failures; documented supply interruptions | Ground-truth where available (sparse) |
| **GDO products** | Structured GDO-vs-GloFAS benchmark (Decision 8) — which better tracks observed WASH impacts while staying globally consistent |

Tuning outputs: recommended SRI threshold, accumulation period, and duration rule; a short validation note recording agreement statistics and the chosen defaults. Reuse `hazard_band_diagnostic.py` where possible for band comparisons.

---

## 10. Risks and limitations

| Risk / limitation | Impact | Mitigation |
|---|---|---|
| GloFAS is a river-network model; overlaying on all population cells misattributes exposure | High — biases the headline % | Explicit contributing-area/nearest-river logic in Stage 4 (§6 caveat); document assumption in sidecar |
| Runoff variable may not be distributed → fall back to SSI on discharge | Medium — conceptual drift from note | Confirm catalogue early; document substitution; both are standardised anomalies |
| Distribution fitting fails on intermittent/zero-flow rivers | Medium — arid-zone artefacts | Empirical/mixed distribution; QA arid pilots (NER, SOM) |
| Coarse GloFAS grid vs fine WorldPop → resampling artefacts | Medium | Aggregate at Admin2 (coarse target absorbs some error); record resampling method |
| Hydrological drought is *necessary but not sufficient* for WASH impact | Interpretation | Keep the note's interpretation caveat in outputs; label as *exposure to* severe hydrological drought, not *impact* |
| EWDS/CDS migration and API/latency changes | Delivery | Verify endpoint at Phase 1; pin client versions |
| Boundary/p-code mismatches (e.g. CAF offset, MOZ unit count) | Join loss | Reuse existing crosswalks and the validator's fail-loud join reporting |

---

## 11. Phasing and indicative effort

| Phase | Tasks | Output | Depends on | Indicative effort |
|---|---|---|---|---|
| **0. Confirm design** | Resolve Decisions 1–8 against the live GloFAS catalogue; confirm variable, product, baseline, endpoint | Signed-off design note | — | ~2–3 days |
| **1. Prototype processor** | Build Stages 1–5 for one pilot (SOM); resolve the river-cell→population logic; produce first Admin2 table | Working prototype + table | Phase 0 | ~1–1.5 weeks |
| **2. Validate & tune** | Run pilots (SOM, KEN, NER, SSD); compare bands/durations against references; GDO benchmark; set defaults | Validation note; chosen threshold/duration | Phase 1 | ~1.5–2 weeks |
| **3. Productionise** | Generalise the runner; wire registry, `stage_country.py`, sidecar, validator | Reproducible per-country pipeline | Phase 2 | ~1 week |
| **4. Integrate & decide slot** | Add `--hydrodrought` to the integrator; decide replace vs parallel HI‑07; document | Populated WIA Data files; decision logged in `_context/DECISIONS.md` | Phase 3 | ~2–3 days |
| **5. Roll-out** | Batch across active countries; refresh sidecars/manifests | Countries carrying the indicator | Phase 4 | Ongoing, per roll-out cadence |

Total to production-ready (Phases 0–4): approximately **4–6 weeks** of focused effort, excluding roll-out. *(Confidence: medium — the river-cell→population logic in Phase 1 is the main schedule risk.)*

---

## 12. Open questions for James

1. **Indicator slot (Decision 1):** build as a parallel `hydrodrought` table first, or commit to replacing SPEI HI‑07 up front?
2. **Variable (Decision 2):** is there a prior preference for SRI-on-runoff versus SSI-on-discharge, or should this be catalogue-led?
3. **Who owns Layer A?** Should the GloFAS processor sit with Alberto's geospatial/GEE workstream (consistent with flood/heat), or be built as a standalone in `Hazard Code/`?
4. **Pilot set:** are SOM, KEN, NER, SSD (+AFG) the right validation countries, given available MSNA/assessment evidence?
5. **GDO comparison:** run it as a blocking gate before adoption, or in parallel as the methodology suggests?

---

### References
- WMO. *Handbook of Drought Indicators and Indices* (WMO‑No. 1173). https://library.wmo.int/idurl/4/56255
- Copernicus CEMS. *Global Flood Awareness System (GloFAS)*. https://ewds.climate.copernicus.eu/datasets/cems-glofas-historical
- Copernicus CEMS. *Global Drought Observatory (GDO)*. https://drought.emergency.copernicus.eu/
- WorldPop. https://www.worldpop.org/
- In-project: `wia-stage-inputs` skill (`source_registry.yaml`, `file_format.md`), `Data & Analysis/Hazard Code/integrate_hazard_to_wia.py`, current SPEI HI‑07 staging (`drought.csv`).
