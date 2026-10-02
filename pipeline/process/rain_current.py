"""Phase 2: current-year rainfall and the district rain metrics.

1. Real-time IMD daily grids for the current year -> district daily mm
   (data/processed/rain_current_daily.parquet). The last REFRESH_DAYS days are
   re-downloaded every run because the newest files can be preliminary.
2. Metrics per district as of the latest available day:
   - season-to-date actual vs normal (daily normals, NORMAL_PERIOD), departure %,
     IMD category
   - SPI-3 and SPI-6 for the last complete month (gamma fit per district and
     calendar month over the normal period)
   Written to web/data/rain.json.

Seasons: SW monsoon Jun 1 - Sep 30 for all districts; NE monsoon Oct 1 - Dec 31
for districts listed in data/reference/ne_monsoon_districts.csv. Outside a
district's season, the most recent completed season is reported.

Usage: python -m pipeline.process.rain_current [--year 2026] [--no-download]
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from pipeline.process.rain import NORMAL_PERIOD, PROC, REF, load_weights, to_districts
from pipeline.sources import imd

REPO = Path(__file__).resolve().parents[2]
WEB = REPO / "web" / "data"
IST = timezone(timedelta(hours=5, minutes=30))
REFRESH_DAYS = 7
SPI_MIN_YEARS = 30

log = logging.getLogger("rain_current")

# IMD departure categories (percent), as used in IMD district rainfall reports.
CATEGORIES = [(60, "Large Excess"), (20, "Excess"), (-19, "Normal"), (-59, "Deficient"), (-99, "Large Deficient")]


def category(dep: float | None) -> str | None:
    if dep is None or np.isnan(dep):
        return None
    d = round(dep)
    for floor, name in CATEGORIES:
        if d >= floor:
            return name
    return "No Rain"


# ---------- current-year daily ----------

def update_daily(year: int, download: bool) -> pd.DataFrame:
    out = PROC / "rain_current_daily.parquet"
    old = pd.read_parquet(out) if out.exists() else pd.DataFrame()
    if not old.empty and pd.to_datetime(old.date).dt.year.max() != year:
        old = pd.DataFrame()
    have = set(pd.to_datetime(old.date).dt.date) if not old.empty else set()

    today = datetime.now(IST).date()
    end = min(today, date(year, 12, 31))
    W, codes = load_weights()
    rows = []
    day = date(year, 1, 1)
    while day <= end:
        recent = (end - day).days < REFRESH_DAYS
        if download and (day not in have or recent):
            try:
                p = imd.day_file(day, refresh=recent)
            except imd.ImdError as exc:
                if (end - day).days <= 2:  # today's/yesterday's file may not be published yet
                    log.info("not yet available: %s", day)
                    day += timedelta(days=1)
                    continue
                raise
            v = to_districts(imd.read(p), W)[0]
            rows.append(pd.DataFrame({"date": pd.Timestamp(day), "dist_lgd": codes, "mm": v.astype("float32")}))
        day += timedelta(days=1)
    if rows:
        new = pd.concat(rows, ignore_index=True)
        keep = old[~pd.to_datetime(old.date).isin(new.date.unique())] if not old.empty else old
        df = pd.concat([keep, new], ignore_index=True).sort_values(["date", "dist_lgd"])
        df.to_parquet(out, index=False)
        return df
    return old


# ---------- seasons ----------

def ne_districts() -> set[int]:
    p = REF / "ne_monsoon_districts.csv"
    return set(pd.read_csv(p).dist_lgd) if p.exists() else set()


def season_window(as_of: date, ne: bool) -> tuple[str, date, date]:
    y = as_of.year
    if ne and as_of.month >= 10:
        return "NE", date(y, 10, 1), as_of
    if ne and as_of.month <= 5:
        return "NE", date(y - 1, 10, 1), date(y - 1, 12, 31)
    if 6 <= as_of.month <= 9:
        return "SW", date(y, 6, 1), as_of
    if as_of.month >= 10:
        return "SW", date(y, 6, 1), date(y, 9, 30)
    return "SW", date(y - 1, 6, 1), date(y - 1, 9, 30)


def normal_sum(normals: pd.DataFrame, start: date, end: date) -> pd.Series:
    days = pd.date_range(start, end, freq="D")
    key = pd.MultiIndex.from_arrays([days.month, days.day])
    n = normals.set_index(["month", "day", "dist_lgd"]).mm.unstack()
    return n.reindex(key).sum(min_count=1)


# ---------- SPI ----------

def spi(monthly: pd.DataFrame, scale: int, end_year: int, end_month: int) -> pd.Series:
    """SPI for the `scale`-month window ending end_year/end_month, per district.
    Gamma fit (zero-inflated) on the same window over NORMAL_PERIOD years."""
    m = monthly.copy()
    m["t"] = m.year * 12 + (m.month - 1)
    wide = m.pivot(index="t", columns="dist_lgd", values="mm").sort_index()
    roll = wide.rolling(scale, min_periods=scale).sum()
    out = {}
    target = end_year * 12 + end_month - 1
    if target not in roll.index:
        return pd.Series(dtype=float)
    base_t = [y * 12 + end_month - 1 for y in range(NORMAL_PERIOD[0], NORMAL_PERIOD[1] + 1)]
    base = roll.reindex(base_t)
    for code in roll.columns:
        x = base[code].dropna().to_numpy()
        v = roll.at[target, code]
        if len(x) < SPI_MIN_YEARS or np.isnan(v):
            continue
        q = np.mean(x == 0)
        pos = x[x > 0]
        if len(pos) < SPI_MIN_YEARS // 2:
            continue
        a, _, scale_ = stats.gamma.fit(pos, floc=0)
        p = q + (1 - q) * (stats.gamma.cdf(v, a, scale=scale_) if v > 0 else 0)
        out[code] = float(np.clip(stats.norm.ppf(np.clip(p, 1e-6, 1 - 1e-6)), -3.5, 3.5))
    return pd.Series(out)


def metrics(daily: pd.DataFrame) -> dict:
    daily = daily.assign(date=pd.to_datetime(daily.date))
    as_of = daily.date.max().date()
    normals = pd.read_parquet(PROC / "rain_daily_normal.parquet")
    hist = pd.read_parquet(PROC / "rain_monthly.parquet")
    master = pd.read_csv(REF / "district_master.csv")
    ne = ne_districts()
    act = daily.set_index(["date", "dist_lgd"]).mm.unstack()

    # Monthly series = history + current-year complete months (real-time grids).
    cur = daily[daily.date < pd.Timestamp(as_of.year, as_of.month, 1)]
    cur_m = cur.groupby([cur.date.dt.year.rename("year"), cur.date.dt.month.rename("month"), "dist_lgd"]).mm.sum(min_count=1).reset_index()
    monthly = pd.concat([hist[hist.year < as_of.year], cur_m], ignore_index=True)
    last = pd.Timestamp(as_of.year, as_of.month, 1) - pd.Timedelta(days=1)
    spi3, spi6 = spi(monthly, 3, last.year, last.month), spi(monthly, 6, last.year, last.month)

    official = load_official()
    from pipeline.process import rain_indicators as ri
    from pipeline.process.rain_weekly import weekly_from_daily
    weekly = pd.read_parquet(PROC / "rain_weekly.parquet")
    weekly = pd.concat([weekly[weekly.year < as_of.year], weekly_from_daily(act)], ignore_index=True)
    wnormal = pd.read_parquet(PROC / "rain_weekly_normal.parquet")
    ind = {}  # (start, end) -> (dry spell weeks, season SPI)

    out = {}
    for code in master.dist_lgd:
        is_ne = code in ne
        season, start, end = season_window(as_of, is_ne)
        if (start, end) not in ind:
            ind[(start, end)] = (ri.dry_spells(weekly, wnormal, start, end), ri.season_spi(monthly, start, end))
        spells, sspi = ind[(start, end)]
        g = {"actual_mm": None, "normal_mm": None, "departure_pct": None, "category": None}
        if code in act.columns:
            if pd.Timestamp(start).year == as_of.year:
                a_ = act.loc[pd.Timestamp(start):pd.Timestamp(end), code].sum(min_count=1)
            else:  # previous year's season comes from the history file
                h = hist[(hist.dist_lgd == code) & (hist.year == start.year) & hist.month.between(start.month, end.month)]
                a_ = h.mm.sum(min_count=1)
            nrm = normal_sum(normals[normals.dist_lgd == code], start, end).get(code, np.nan)
            dep = (a_ - nrm) / nrm * 100 if nrm and not np.isnan(nrm) and nrm > 0 else np.nan
            g = {"actual_mm": _r(a_, 1), "normal_mm": _r(nrm, 1), "departure_pct": _r(dep, 0), "category": category(dep)}
        imd_row = official.get((season, str(start), str(end) if end < as_of else None), {}).get(code)
        if imd_row is not None and imd_row.get("departure_pct") is not None:
            head, src = imd_row, "IMD"
        elif g["departure_pct"] is not None:
            head, src = g, "gridded"
        else:
            head, src = {"actual_mm": None, "normal_mm": None, "departure_pct": None, "category": None}, None
        out[int(code)] = {
            "season": season, "start": str(start), "end": str(end),
            "season_days": (end - start).days + 1,
            "source": src, **{k: head.get(k) for k in ("actual_mm", "normal_mm", "departure_pct", "category")},
            "gridded": g,
            "spi3": None if code not in spi3 else round(spi3[code], 2),
            "spi6": None if code not in spi6 else round(spi6[code], 2),
            "spi_season": None if code not in sspi else round(float(sspi[code]), 2),
            "dry_spell_weeks": None if code not in spells else int(spells[code]),
        }
        short, why = ri.rain_short(head.get("category"), out[int(code)]["spi_season"], out[int(code)]["dry_spell_weeks"])
        out[int(code)].update(short=short, short_reasons=why)
    no_cov = [c for c, d in out.items() if d["source"] is None]
    srcs = pd.Series([d["source"] for d in out.values()]).value_counts(dropna=False).to_dict()
    return {
        "as_of": str(as_of), "spi_month": f"{last.year}-{last.month:02d}",
        "normal_period": f"{NORMAL_PERIOD[0]}-{NORMAL_PERIOD[1]}",
        "source": "Headline: IMD official district figures (mausam.imd.gov.in), else IMD 0.25 deg gridded "
                  "rainfall averaged over the district ('gridded'). SPI from gridded data.",
        "headline_sources": {str(k): v for k, v in srcs.items()},
        "no_coverage": sorted(no_cov),
        "districts": out,
    }


def _r(x, nd):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), nd) if nd else int(round(float(x)))


def load_official() -> dict:
    """{(season, start, end-or-None-if-running): {dist_lgd: {...}}} from rain_official.py outputs."""
    d = PROC / "imd_official"
    out = {}

    def rows(df):
        r = {}
        for x in df.itertuples():
            dep = getattr(x, "period_dep_pct", None)
            if dep is None or pd.isna(dep):
                continue
            r[int(x.dist_lgd)] = {"actual_mm": _r(getattr(x, "period_actual_mm", None), 1),
                                 "normal_mm": _r(getattr(x, "period_normal_mm", None), 1),
                                 "departure_pct": int(round(dep)), "category": x.category}
        return r

    for p in d.glob("season_*_*.csv"):
        df = pd.read_csv(p)
        y, s = p.stem.split("_")[1:]
        start = df.period_start.iloc[0]
        out[(s, start, df.period_end.iloc[0])] = rows(df)
    if (d / "latest.csv").exists():
        df = pd.read_csv(d / "latest.csv")
        st = date.fromisoformat(df.period_start.iloc[0])
        s = {(6, 1): "SW", (10, 1): "NE"}.get((st.month, st.day))
        if s:
            out[(s, str(st), None)] = rows(df)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.now(IST).year)
    ap.add_argument("--no-download", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    daily = update_daily(a.year, not a.no_download)
    if daily.empty:
        raise SystemExit("no current-year rainfall data")
    m = metrics(daily)
    WEB.mkdir(parents=True, exist_ok=True)
    (WEB / "rain.json").write_text(json.dumps(m, separators=(",", ":")))
    cats = pd.Series([d["category"] for d in m["districts"].values()]).value_counts()
    log.info("as of %s: %s; headline sources %s", m["as_of"], cats.to_dict(), m["headline_sources"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
