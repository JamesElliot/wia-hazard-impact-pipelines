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

ap = argparse.ArgumentParser()
ap.add_argument("--reach-xlsx", required=True)
ap.add_argument("--cold-table", required=True)
args = ap.parse_args()
f, cold_csv = args.reach_xlsx, args.cold_table
d=pd.read_excel(f,sheet_name="District-Level Cold Wave Events",header=None)
months=["Sep","Oct","Nov","Dec","Jan","Feb","Mar"]
rows=d.iloc[3:].dropna(subset=[3]).copy()
out=pd.DataFrame({"code":rows[3].astype(str).str.strip(),"district":rows[2],"province":rows[1]})
for i,m in enumerate(months):
    for s in range(4):
        out[f"{m}_s{s+1}"]=pd.to_numeric(rows[5+5*i+s],errors="coerce").values
sums=out[[f"Sep_s{s}" for s in range(1,5)]].sum(axis=1); print("rows",len(out),"row sums ok:",(sums==27).mean())
djf=["Dec","Jan","Feb"]
out["reach_s34_DJF"]=np.mean([out[f"{m}_s3"]+out[f"{m}_s4"] for m in djf],axis=0)   # mean winters (of 27) at sev 3-4
out["reach_s4_DJF"]=np.mean([out[f"{m}_s4"] for m in djf],axis=0)
out["reach_s234_DJF"]=np.mean([out[f"{m}_s2"]+out[f"{m}_s3"]+out[f"{m}_s4"] for m in djf],axis=0)
out["reach_s34_any"]=np.max([out[f"{m}_s3"]+out[f"{m}_s4"] for m in months],axis=0)
c=pd.read_csv(cold_csv)
print("our code sample",c.adm2_pcode.head(3).tolist(),"reach",out.code.head(3).tolist())
m=out.merge(c,left_on="code",right_on="adm2_pcode",how="inner"); print("matched",len(m),"of",len(out),len(c))
print("unmatched reach:",sorted(set(out.code)-set(c.adm2_pcode))[:10],"unmatched ours:",sorted(set(c.adm2_pcode)-set(out.code))[:10])
ours=["pct_exposed_cold_m13c","pct_exposed_cold_m27c","pct_exposed_cold_m40c"]
theirs=["reach_s34_DJF","reach_s4_DJF","reach_s234_DJF","reach_s34_any"]
res=pd.DataFrame({t:[m[o].corr(m[t],method="spearman") for o in ours] for t in theirs},index=ours); print(res.round(2))
print(m[theirs].describe().loc[["mean","50%","max"]].round(1))
# popweighted view: pop in reach top severity band
w=m.pop_total
for t in ["reach_s34_DJF","reach_s4_DJF"]:
    print(t,"pop share with >=1 winter in DJF sev34:", round(w[m[t]>0].sum()/w.sum()*100,1))
# agreement: high vs low
q=m.reach_s34_DJF.rank(pct=True)
for o in ours: print(o,"mean pct in REACH top-quartile: %.0f, bottom half: %.0f"%(m.loc[q>0.75,o].mean(), m.loc[q<=0.5,o].mean()))
