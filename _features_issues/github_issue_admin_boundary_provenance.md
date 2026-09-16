# GitHub issue — admin boundary provenance

Prepared 2026-07-29. File on **both** `JamesElliot/wia-hazard-impact-pipelines` and `beto-Sibileau/wia-scripts`.
Body below is common to both; §5 has the per-repo delta. Suggested labels: `bug`, `output-contract`, `provenance`.

---

## Title

**Outputs do not record which administrative boundary set they were built against**

---

## Summary

Neither pipeline records, in a machine-readable and unambiguous way, **which administrative boundary dataset an output table was aggregated to**. Outputs can therefore be silently produced against different admin sets for the same country and admin level, and there is no way to detect this from the emitted tables.

This is not hypothetical. It has already produced incorrect indicator values in the WIA country roll-out, and it is currently blocking a boundary re-run programme across nine countries.

---

## Why this matters

Every WIA hazard indicator is a population-weighted aggregate to an admin unit, joined into the WIA Data file on a p-code. If the pipeline aggregates to a different admin vintage from the one the WIA model uses, the join silently drops or misattributes units. The output looks entirely valid — correct column names, values in range, plausible distribution — and the failure is invisible without manual row-count comparison.

Observed consequences to date:

| Country | Symptom |
|---|---|
| CAF | Hazard tables on 72 units vs a 85-unit model spine; required a bespoke spatial reconciliation to recover |
| COD | 189 units vs 164 territoires; required a hand-built p-code crosswalk |
| MLI | 53 units vs a 161-unit spine — **fails the WIA 50% validity gate**, indicators unusable |

Each was diagnosed by hand, weeks after the outputs were produced.

---

## Evidence

### Exhibit A — impact pipeline records nothing about boundaries

`run_metadata.json` from an AFG drought run (`2026-06-30_m12`):

```json
"run_config": {
  "hazard": "drought", "iso3": "AFG", "as_of_date": "2026-06-30",
  "lookback_months": 12, "window_start": "2025-07-01", "window_end": "2026-06-30",
  "target_adm_level": 2, "buffer_km": 0.0
}
```

Searching the full document for `boundar`, `geojson`, `shp` or `cod` returns **no matches** relating to an admin source. The only trace of the admin set is `admin_table_spei.n_admin2: 401` — a unit count, which cannot identify a boundary set (two different vintages can share a count) and is buried in a nested QC block.

### Exhibit B — exposure pipeline records the asset, but not its authority or vintage

`run_log_afg_adm2.json` does better:

```json
"admin_boundaries": {
  "asset_id": "projects/unicef-ccri/assets/misc_boundaries/AFG_adm2",
  "gee_id_field": "adm2_pcode", "output_id_field": "adm2_pcode",
  "id_field_renamed": false, "n_features": 401
}
```

This identifies *an asset*, but not **which authority's boundaries it holds, which vintage, or when it was accessed**. `misc_boundaries/AFG_adm2` may be COD-AB, GADM, or a bespoke set — the consumer cannot tell. It is also recorded once per run folder rather than per emitted table, so a table separated from its folder carries no provenance at all.

### Exhibit C — the collision this permits (CAF)

CAF exposure was run against two different boundary sets:

```
run_log_caf_adm2.json      → .../misc_boundaries/CAF_adm2      n_features: 72
run_log_caf_adm2_new.json  → .../misc_boundaries/CAF_adm2_new  n_features: 85
```

Both output sets were written into the **same** `Indicators_and_Maps/` directory:

```
CAF_adm2_2025_river_flood_100yr_jrc_2024_exp_abs.xlsx        72 rows
CAF_adm2_NEW_2025_river_flood_100yr_jrc_2024_exp_abs.xlsx    85 rows
```

Two points:

1. The only thing distinguishing them is an ad-hoc uppercase `NEW` inserted into the filename. It is not part of any naming grammar, it is not in the metadata schema, and it would not survive a rename.
2. **Both files carry the identical internal sheet name `CAF_adm2_2025`.** Opened in Excel, the two are indistinguishable.

A downstream consolidation script selecting `CAF_adm2_*` by glob picked the 72-row file and produced CAF indicators at 63/86 coverage, while the correct 85-row table sat beside it. That is exactly the failure mode this issue is about.

---

## Proposed change

Add a required `admin_source` block to the run metadata emitted by both pipelines, and propagate a vintage token into output filenames.

```json
"admin_source": {
  "authority":    "COD",
  "vintage":      "COD2026-06",
  "access_date":  "2026-06-14",
  "path":         "admin/afg_adm2_COD2026-06.geojson",
  "asset_id":     "projects/unicef-ccri/assets/misc_boundaries/AFG_adm2",
  "sha256":       "9f2c…",
  "admin_level":  2,
  "unit_count":   401,
  "pcode_field":  "adm2_pcode"
}
```

### Vintage token convention

`<AUTHORITY><YYYY-MM>` — authority code plus year-month of access.

| Token | Meaning |
|---|---|
| `COD2026-06` | OCHA Common Operational Dataset, accessed June 2026 (WIA standard) |
| `GADM2026-06` | GADM, accessed June 2026 |
| `NSO2026-06` | National statistical office boundaries |

The authority prefix is deliberate: it makes non-OCHA boundaries visible at a glance rather than requiring the metadata to be opened.

### Filename propagation

The token should appear in emitted table filenames so provenance survives a file being copied out of its run directory:

```
AFG_drought_adm2_COD2026-06_2026-06-30_m12.csv        (impact)
AFG_river_flood_100yr_jrc_2024_adm2_COD2026-06.csv    (exposure)
```

For `.xlsx` outputs, the **internal sheet name must carry the same token** — Exhibit C shows that identical sheet names across vintages actively mislead.

---

## Per-repo notes

**`wia-hazard-impact-pipelines`** — `docs/output-contract.md` already states that *"dataset-specific provenance remains mandatory for production publication"*, and the administrative summary field table already defines `admin_level` and `admin_pcode`. This is a **gap against the existing contract**, not a new requirement. Suggested work: extend `run_config`/`run_metadata` with `admin_source`, validate it in `schemas/run_metadata.schema.json`, and add the token to the `tables/` filename.

**`wia-scripts`** — the `admin_boundaries` block in `run_log_*.json` is most of the way there; it needs `authority`, `vintage`, `access_date` and a checksum, plus propagation into `postprocess_*` outputs, the emitted xlsx/csv filenames, and the internal sheet name. The `_new` suffix convention should be retired in favour of the vintage token.

---

## Acceptance criteria

- [ ] `admin_source` is present in run metadata for every hazard in both pipelines, and is schema-validated.
- [ ] A run fails fast with a clear error if the admin source cannot be resolved to an authority and vintage.
- [ ] The vintage token appears in every emitted table filename, and in the internal sheet name of every emitted `.xlsx`.
- [ ] Two runs of the same country, hazard and window against different boundary sets produce **non-colliding** output filenames.
- [ ] A consumer can determine the boundary set of a single table file without access to the run directory.
- [ ] `docs/output-contract.md` (impact repo) documents `admin_source` as mandatory.

---

## Backward compatibility

Existing outputs have no `admin_source`. Suggest treating absence as `"vintage": "unknown"` rather than failing on read, so the nine already-built WIA country tables remain loadable while re-runs proceed. New runs should hard-fail.

---

## Related

- WIA hazard consolidation spec: `Data & Analysis/Hazard/wia_hazard_consolidation_spec.yaml`
- Per-country reconciliation currently required: CAF (spatial overlay), COD (p-code crosswalk), MLI (unresolved, fails validity gate)
