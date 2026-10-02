"""IMD's official district rainfall figures (the site's headline rain number).

IMD republishes its district PDFs every day for the current IMD season
(Jan 1, Mar 1, Jun 1, Oct 1 starts) and overwrites them, so we archive:
  data/processed/imd_official/latest.csv              today's season-to-date table
  data/processed/imd_official/season_<year>_<SW|NE>.csv   final figures for a season,
      written on its last day (from the daily table, with mm), or, if that day was
      missed, from the week-by-week cumulative PDF (departure % only)

Districts IMD doesn't list, or prints as ND, fall back to our gridded value
(rain_current.py marks the source).

Usage: python -m pipeline.process.rain_official [--no-download]
"""

from __future__ import annotations

import argparse
import logging
import re
from datetime import date
from pathlib import Path

import pandas as pd

from pipeline.validate import imd_district as v

REPO = Path(__file__).resolve().parents[2]
REF = REPO / "data" / "reference"
OUT = REPO / "data" / "processed" / "imd_official"
SEASON_END = {"SW": (9, 30), "NE": (12, 31)}
SEASON_START = {"SW": (6, 1), "NE": (10, 1)}  # IMD's post-monsoon season (Oct-Dec) is the NE season
CAT = {"LE": "Large Excess", "E": "Excess", "N": "Normal", "D": "Deficient", "LD": "Large Deficient",
       "NR": "No Rain", "ND": None}

log = logging.getLogger("rain_official")


def crosswalk() -> pd.DataFrame:
    x = pd.read_csv(REF / "imd_districts.csv")
    return x[(x.relation == "one")].dropna(subset=["dist_lgd"])[["state", "imd_name", "dist_lgd"]]


def daily_table(download: bool) -> pd.DataFrame:
    pdf = v.fetch(v.CD) if download else v.DIR / v.CD
    start, end, t = v.district_table(pdf)
    t["state"] = t.state.str.replace("TAMILNADU", "TAMIL NADU")
    t = t.merge(crosswalk(), on=["state", "imd_name"], how="left")
    unmatched = t[t.dist_lgd.isna() & (t.imd_name != "")]
    if len(unmatched):
        log.warning("IMD districts with no LGD match: %s", unmatched.imd_name.tolist())
    t = t.dropna(subset=["dist_lgd"]).astype({"dist_lgd": int})
    t.insert(0, "period_start", start)
    t.insert(1, "period_end", end)
    t["category"] = t.period_cat.map(CAT)
    return t


def season_of(start: str) -> str | None:
    d = date.fromisoformat(start)
    for s, (m, dd) in SEASON_START.items():
        if (d.month, d.day) == (m, dd):
            return s
    return None


def save_season_from_daily(t: pd.DataFrame) -> None:
    s = season_of(t.period_start.iloc[0])
    end = date.fromisoformat(t.period_end.iloc[0])
    if s and (end.month, end.day) == SEASON_END[s]:
        p = OUT / f"season_{end.year}_{s}.csv"
        t.assign(source="IMD daily district table").to_csv(p, index=False)
        log.info("saved final %s %s season from daily table (%d districts)", end.year, s, len(t))


def save_season_from_cumulative(download: bool) -> None:
    """Back-fill a just-finished season from the week-by-week cumulative PDF."""
    pdf = v.fetch(v.CUM) if download else v.DIR / v.CUM
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})\s+To\s+(\d{2})-(\d{2})-(\d{4})", v.period(pdf))
    if not m:
        return
    start = f"{m[3]}-{m[2]}-{m[1]}"
    end = date(int(m[6]), int(m[5]), int(m[4]))
    s = season_of(start)
    if not s or (end.month, end.day) != SEASON_END[s]:
        return  # season still running: the daily table covers it
    p = OUT / f"season_{end.year}_{s}.csv"
    if p.exists():
        return
    c = v.cumulative_last(pdf)
    x = crosswalk()
    x = x[~x.imd_name.duplicated(keep=False)]  # names used in two states can't be placed without a state
    c = c[~c.imd_name.duplicated(keep=False)].merge(x, on="imd_name", how="inner")
    c = c.rename(columns={"imd_dep_pct": "period_dep_pct"})
    c["period_start"], c["period_end"] = start, str(end)
    c["category"] = c.period_dep_pct.map(lambda d: None if pd.isna(d) else _cat(d))
    c["source"] = "IMD week-by-week cumulative table (departure only)"
    c[["period_start", "period_end", "state", "imd_name", "dist_lgd", "period_dep_pct", "category", "source"]].to_csv(p, index=False)
    log.info("saved final %s %s season from cumulative table (%d districts)", end.year, s, len(c))


def _cat(d: float) -> str:
    from pipeline.process.rain_current import category
    return category(d)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-download", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    OUT.mkdir(parents=True, exist_ok=True)
    t = daily_table(not a.no_download)
    t.to_csv(OUT / "latest.csv", index=False)
    log.info("IMD period %s to %s: %d districts", t.period_start.iloc[0], t.period_end.iloc[0], len(t))
    save_season_from_daily(t)
    save_season_from_cumulative(not a.no_download)
    save_snapshot(t)
    return 0


# Dates the history snapshots use (groundwater cycle ends) plus season ends.
SNAPSHOT_DAYS = {(1, 31), (5, 31), (8, 31), (11, 30), (9, 30), (12, 31)}


def save_snapshot(t: pd.DataFrame) -> None:
    """Keep IMD's season-to-date table permanently when its period ends on a snapshot date."""
    end = date.fromisoformat(t.period_end.iloc[0])
    if (end.month, end.day) in SNAPSHOT_DAYS:
        p = OUT / f"snapshot_{end}.csv"
        t.to_csv(p, index=False)
        log.info("saved snapshot %s", p.name)


if __name__ == "__main__":
    raise SystemExit(main())
