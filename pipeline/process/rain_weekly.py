"""Weekly district rainfall (IMD standard meteorological weeks) for dry-spell detection.

Standard meteorological week (SMW) k covers day-of-year 7(k-1)+1 .. 7k; week 52 absorbs the
last 1-2 days of the year (Dec 24-31), so Feb 29 shifts later weeks by a day in leap years,
as in IMD's convention.

Inputs:  data/raw/imd/reduced/<year>.parquet (daily district series, local) for history,
         data/processed/rain_current_daily.parquet for the current year
Outputs: data/processed/rain_weekly.parquet          dist_lgd, year, week, mm   (1971 onward)
         data/processed/rain_weekly_normal.parquet   dist_lgd, week, mm         (1971-2020 mean)
Usage:   python -m pipeline.process.rain_weekly

Without the local daily history (the daily run on a clean checkout), past years are kept
from the existing rain_weekly.parquet and only the current year's weeks are rebuilt from
rain_current_daily.parquet; the normals are left as they are.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.process.rain import NORMAL_PERIOD, PROC

REPO = Path(__file__).resolve().parents[2]
REDUCED = REPO / "data" / "raw" / "imd" / "reduced"
FIRST_YEAR = 1971

log = logging.getLogger("rain_weekly")


def smw(dates: pd.DatetimeIndex) -> np.ndarray:
    return np.minimum((dates.dayofyear - 1) // 7 + 1, 52)


def weekly_from_daily(df: pd.DataFrame) -> pd.DataFrame:
    """df: index = dates, columns = dist_lgd (str or int) -> long weekly sums."""
    w = df.groupby([df.index.year, smw(df.index)]).sum(min_count=1)
    w.index.names = ["year", "week"]
    out = w.stack().rename("mm").reset_index()
    out.columns = ["year", "week", "dist_lgd", "mm"]
    out["dist_lgd"] = out.dist_lgd.astype(int)
    return out


def build() -> None:
    parts = []
    for y in range(FIRST_YEAR, 2100):
        p = REDUCED / f"{y}.parquet"
        if not p.exists():
            break
        parts.append(weekly_from_daily(pd.read_parquet(p)))
    cur = pd.read_parquet(PROC / "rain_current_daily.parquet")
    cur["date"] = pd.to_datetime(cur.date)
    incremental = not parts
    if incremental:
        old = pd.read_parquet(PROC / "rain_weekly.parquet")
        parts.append(old[old.year < cur.date.dt.year.min()])
        last_hist = int(cur.date.dt.year.min()) - 1
    else:
        last_hist = FIRST_YEAR + len(parts) - 1
    cur = cur[cur.date.dt.year > last_hist].pivot(index="date", columns="dist_lgd", values="mm")
    if len(cur):
        parts.append(weekly_from_daily(cur))
    w = pd.concat(parts, ignore_index=True).astype({"year": "int16", "week": "int8", "dist_lgd": "int32"})
    w["mm"] = w.mm.astype("float32").round(2)
    w.to_parquet(PROC / "rain_weekly.parquet", index=False)
    if incremental:
        log.info("weekly rain (incremental): past years kept, %d rebuilt; %d rows", last_hist + 1, len(w))
        return
    n = w[w.year.between(*NORMAL_PERIOD)].groupby(["dist_lgd", "week"]).mm.mean().rename("mm").reset_index()
    n["mm"] = n.mm.astype("float32")
    n.to_parquet(PROC / "rain_weekly_normal.parquet", index=False)
    log.info("weekly rain: %d-%d, %d rows; normals %d rows", FIRST_YEAR, w.year.max(), len(w), len(n))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    build()
