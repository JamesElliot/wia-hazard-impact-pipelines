#!/usr/bin/env python3
"""Compare the UTCI cold table for AFG with REACH's ERA5/SMI cold-wave winter counts.

Usage: validate_cold_vs_reach.py --reach-xlsx <REACH database.xlsx> --cold-table <cold table csv>

REACH severity is an anomaly rule (SD below the district's own climate, plus an absolute cap for
severity 3-4); the UTCI cold layer is absolute. Spearman rank correlation across districts is a
consistency check, not a like-for-like validation.
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

MONTHS = ["Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]
DJF = ["Dec", "Jan", "Feb"]
OURS = ["pct_exposed_cold_m13c", "pct_exposed_cold_m27c", "pct_exposed_cold_m40c"]
THEIRS = ["reach_s34_DJF", "reach_s4_DJF", "reach_s234_DJF", "reach_s34_any"]


def load_reach(xlsx: str) -> pd.DataFrame:
    """District sheet: per month, four columns = number of the 27 winters at severity 1-4."""
    raw = pd.read_excel(xlsx, sheet_name="District-Level Cold Wave Events", header=None)
    rows = raw.iloc[3:].dropna(subset=[3])
    out = pd.DataFrame(
        {
            "code": rows[3].astype(str).str.strip(),
            "district": rows[2],
            "province": rows[1],
        }
    )
    for i, month in enumerate(MONTHS):
        for sev in range(4):
            out[f"{month}_s{sev + 1}"] = pd.to_numeric(rows[5 + 5 * i + sev], errors="coerce").values
    sev34 = {m: out[f"{m}_s3"] + out[f"{m}_s4"] for m in MONTHS}
    sev234 = {m: out[f"{m}_s2"] + out[f"{m}_s3"] + out[f"{m}_s4"] for m in DJF}
    out["reach_s34_DJF"] = np.mean([sev34[m] for m in DJF], axis=0)  # mean winters (of 27)
    out["reach_s4_DJF"] = np.mean([out[f"{m}_s4"] for m in DJF], axis=0)
    out["reach_s234_DJF"] = np.mean([sev234[m] for m in DJF], axis=0)
    out["reach_s34_any"] = np.max([sev34[m] for m in MONTHS], axis=0)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--reach-xlsx", required=True)
    ap.add_argument("--cold-table", required=True)
    args = ap.parse_args()

    reach = load_reach(args.reach_xlsx)
    cold = pd.read_csv(args.cold_table)
    row_sums = reach[[f"Sep_s{s}" for s in range(1, 5)]].sum(axis=1)
    print("rows", len(reach), "row sums ok:", (row_sums == 27).mean())

    merged = reach.merge(cold, left_on="code", right_on="adm2_pcode", how="inner")
    print("matched", len(merged), "of", len(reach), len(cold))
    print("unmatched reach:", sorted(set(reach.code) - set(cold.adm2_pcode))[:10])
    print("unmatched ours:", sorted(set(cold.adm2_pcode) - set(reach.code))[:10])

    corr = pd.DataFrame(
        {t: [merged[o].corr(merged[t], method="spearman") for o in OURS] for t in THEIRS},
        index=OURS,
    )
    print(corr.round(2).to_string())
    print(merged[THEIRS].describe().loc[["mean", "50%", "max"]].round(1).to_string())

    top_quartile = merged.reach_s34_DJF.rank(pct=True) > 0.75
    bottom_half = merged.reach_s34_DJF.rank(pct=True) <= 0.5
    for o in OURS:
        print(
            f"{o}: mean pct exposed in REACH top quartile {merged.loc[top_quartile, o].mean():.0f}, "
            f"bottom half {merged.loc[bottom_half, o].mean():.0f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
