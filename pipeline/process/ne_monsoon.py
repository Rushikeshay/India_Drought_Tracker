"""Districts whose main rainy season is the NE monsoon (Oct-Dec), from IMD's own
district -> met-subdivision grouping.

IMD reports NE-monsoon rainfall for five subdivisions: Coastal Andhra Pradesh &
Yanam, Rayalaseema, Tamil Nadu-Puducherry-Karaikal, South Interior Karnataka,
and Kerala & Mahe.

Step 1 parses IMD's district distribution PDF into data/reference/imd_districts.csv
(IMD name, subdivision, state, dist_lgd). Committed, so later runs don't need the PDF.
Step 2 writes data/reference/ne_monsoon_districts.csv.

Usage: python -m pipeline.process.ne_monsoon [--refresh-pdf]
"""

import argparse
from pathlib import Path

import pandas as pd

from pipeline.validate import imd_district as v

REF = Path(__file__).resolve().parents[2] / "data" / "reference"
NE_SUBDIVISIONS = ["COASTAL ANDHRA PRADESH & YANAM", "RAYALASEEMA", "TAMILNADU & PUDUCHERRY & KARAIKAL",
                   "SOUTHERN INTERIOR KARNATAKA", "KERALA & MAHE"]


def imd_districts(refresh: bool) -> pd.DataFrame:
    pdf = v.fetch(v.CD) if refresh or not (v.DIR / v.CD).exists() else v.DIR / v.CD
    x = v.imd_crosswalk(v.district_groups(pdf))
    x = x[x.name.str.len() > 0]
    out = x[["name", "subdivision", "state", "dist_lgd", "method", "relation"]].rename(columns={"name": "imd_name"})
    out.to_csv(REF / "imd_districts.csv", index=False)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-pdf", action="store_true")
    a = ap.parse_args(argv)
    x = imd_districts(a.refresh_pdf)
    m = pd.read_csv(REF / "district_master.csv")
    ne = x[x.subdivision.isin(NE_SUBDIVISIONS) & (x.relation == "one")].dropna(subset=["dist_lgd"])
    out = m.merge(ne[["dist_lgd", "subdivision"]].astype({"dist_lgd": int}), on="dist_lgd")
    out = out[["dist_lgd", "state", "district", "subdivision"]].sort_values(["state", "district"])
    out.to_csv(REF / "ne_monsoon_districts.csv", index=False)
    print(f"{len(out)} NE-monsoon districts:", out.groupby("state").size().to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
