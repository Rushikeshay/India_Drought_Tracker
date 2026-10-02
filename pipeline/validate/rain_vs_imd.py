"""Phase 2 'done when': our district season departure vs IMD's published figure.

Compares the SW monsoon season-to-date departure (Jun 1 -> end date of IMD's
cumulative table) for every district both sources cover. Our numbers come from
IMD gridded rainfall (real-time) with 1971-2020 daily normals. IMD's come from
station data with its own district normals, so some difference is expected.

Output: notebooks/phase2/rain_vs_imd.csv and a summary printed + saved as JSON.
Usage: python -m pipeline.validate.rain_vs_imd [--refresh-pdf]
"""

import argparse
import json
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.process.rain import PROC, REF
from pipeline.process.rain_current import category, normal_sum
from pipeline.validate import imd_district as v

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "notebooks" / "phase2"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-pdf", action="store_true")
    a = ap.parse_args(argv)
    pdf = v.fetch(v.CUM) if a.refresh_pdf or not (v.DIR / v.CUM).exists() else v.DIR / v.CUM
    per = v.period(pdf)
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})\s+To\s+(\d{2})-(\d{2})-(\d{4})", per)
    start = date(int(m[3]), int(m[2]), int(m[1]))
    end = date(int(m[6]), int(m[5]), int(m[4]))

    imd_tab = v.cumulative_last(pdf)
    names = pd.read_csv(REF / "imd_districts.csv")
    names = names[(names.relation == "one")].dropna(subset=["dist_lgd"])
    imd_tab = imd_tab.merge(names[["imd_name", "dist_lgd", "state"]], on="imd_name", how="inner")
    imd_tab = imd_tab[~imd_tab.imd_name.duplicated(keep=False)]  # same IMD name in two states: skip

    daily = pd.read_parquet(PROC / "rain_current_daily.parquet")
    daily["date"] = pd.to_datetime(daily.date)
    act = daily[(daily.date >= pd.Timestamp(start)) & (daily.date <= pd.Timestamp(end))]
    ndays = act.date.nunique()
    act = act.groupby("dist_lgd").mm.sum(min_count=1)
    normals = pd.read_parquet(PROC / "rain_daily_normal.parquet")
    nrm = normal_sum(normals, start, end)
    ours = ((act - nrm) / nrm * 100).rename("our_dep_pct")

    df = imd_tab.merge(ours.rename_axis("dist_lgd").reset_index(), on="dist_lgd", how="inner")
    df["dist_lgd"] = df.dist_lgd.astype(int)
    df["our_dep_pct"] = df.our_dep_pct.round()
    df["diff_pp"] = df.our_dep_pct - df.imd_dep_pct
    df["imd_cat"] = df.imd_dep_pct.map(category)
    df["our_cat"] = df.our_dep_pct.map(category)
    df = df.dropna(subset=["imd_dep_pct", "our_dep_pct"])
    OUT.mkdir(parents=True, exist_ok=True)
    df.sort_values("diff_pp", key=np.abs, ascending=False).to_csv(OUT / "rain_vs_imd.csv", index=False)

    ad = df.diff_pp.abs()
    summary = {
        "period": f"{start} to {end}", "days_in_our_data": int(ndays), "districts_compared": len(df),
        "median_abs_diff_pp": float(ad.median()), "mean_diff_pp (ours - IMD)": round(float(df.diff_pp.mean()), 1),
        "within_5pp": f"{(ad <= 5).mean():.0%}", "within_10pp": f"{(ad <= 10).mean():.0%}",
        "within_20pp": f"{(ad <= 20).mean():.0%}",
        "same_IMD_category": f"{(df.imd_cat == df.our_cat).mean():.0%}",
        "correlation": round(float(np.corrcoef(df.imd_dep_pct, df.our_dep_pct)[0, 1]), 3),
    }
    (OUT / "rain_vs_imd_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    print(df.reindex(ad.sort_values(ascending=False).index)[["state", "imd_name", "imd_dep_pct", "our_dep_pct", "diff_pp"]].head(15).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
