"""Status history: the district classification at every groundwater cycle end.

Snapshots: Jan 31, May 31 (pre-monsoon / mid-summer), Aug 31, Nov 30 of each year
from START_YEAR, up to the latest cycle that has ended. At each snapshot:
  rain  = the district's current or last completed season at that date
          (rain_current.season_window), departure vs 1971-2020 normals.
          Source: IMD official figures when archived for exactly that window
          (data/processed/imd_official/season_*.csv, snapshot_*.csv), else gridded.
  gw    = groundwater.district_status for that (year, cycle)
  idm   = IDM class of the district mean for the latest week on or before the date (from Jul 2021)
  quadrant via classify.rain_short / gw_low / quadrant

Outputs
  data/processed/status_history.csv   one row per district x snapshot
  web/data/history/index.json, s_<date>.json (one per snapshot), d_<lgd>.json (one per district)
Usage: python -m pipeline.process.history [--start 2000]
"""

from __future__ import annotations

import argparse
import json

from pipeline import webjson
import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.process import groundwater as gw
from pipeline.process import rain_indicators as ri
from pipeline.process.classify import gw_low, quadrant, rain_short
from pipeline.process.stress_history import edition_for
from pipeline.process.rain_current import category, ne_districts, normal_sum, season_window

REPO = Path(__file__).resolve().parents[2]
PROC = REPO / "data" / "processed"
REF = REPO / "data" / "reference"
WEB = REPO / "web" / "data"
START_YEAR = 2000
SNAPSHOTS = [("JAN", 1, 31), ("PRE", 5, 31), ("AUG", 8, 31), ("NOV", 11, 30)]
QCODE = {"fine": "F", "hidden_drought": "H", "buffered": "B", "double_drought": "D", None: None}

log = logging.getLogger("history")


def snapshot_dates(start: int, today: pd.Timestamp) -> list[tuple[date, int, str]]:
    out = []
    for y in range(start, today.year + 1):
        for cyc, m, d in SNAPSHOTS:
            dt = date(y, m, d)
            if pd.Timestamp(dt) < today:
                out.append((dt, y, cyc))
    return out


def monthly_rain() -> pd.DataFrame:
    """History months + current-year complete months from the real-time daily file."""
    hist = pd.read_parquet(PROC / "rain_monthly.parquet")
    cur = pd.read_parquet(PROC / "rain_current_daily.parquet")
    cur["date"] = pd.to_datetime(cur.date)
    last_day = cur.date.max()
    full = cur[cur.date < last_day.to_period("M").to_timestamp()]  # complete months only
    cm = full.groupby([full.date.dt.year.rename("year"), full.date.dt.month.rename("month"), "dist_lgd"]).mm.sum(min_count=1).reset_index()
    cm = cm[~cm.year.isin(hist.year.unique())]
    return pd.concat([hist, cm], ignore_index=True)


def official_windows() -> dict[tuple[str, str], dict[int, tuple[float, str]]]:
    out = {}
    d = PROC / "imd_official"
    for p in list(d.glob("season_*.csv")) + list(d.glob("snapshot_*.csv")):
        t = pd.read_csv(p).dropna(subset=["period_dep_pct"])
        key = (str(t.period_start.iloc[0]), str(t.period_end.iloc[0]))
        out[key] = {int(r.dist_lgd): (float(r.period_dep_pct), r.category) for r in t.itertuples()}
    return out


def build(start: int, today: pd.Timestamp) -> pd.DataFrame:
    master = pd.read_csv(REF / "district_master.csv")
    ne = ne_districts()
    mon = monthly_rain()
    mon["ym"] = mon.year * 12 + mon.month - 1
    normals = pd.read_parquet(PROC / "rain_daily_normal.parquet")
    weekly = pd.read_parquet(PROC / "rain_weekly.parquet")
    wnormal = pd.read_parquet(PROC / "rain_weekly_normal.parquet")
    official = official_windows()
    eds = pd.read_csv(PROC / "ingres_editions.csv").set_index(["edition", "dist_lgd"])
    c, units = gw.series()
    idm = pd.read_parquet(PROC / "idm_weekly.parquet")
    idm["cls"] = pd.cut(idm.cdi_mean, [-np.inf, -2.0, -1.6, -1.3, -0.8, -0.5, np.inf],
                        labels=["d4", "d3", "d2", "d1", "d0", "none"], right=True).astype(str)
    idm.loc[idm.cdi_mean.isna(), "cls"] = None

    rows = []
    for snap, year, cyc in snapshot_dates(start, today):
        g = gw.district_status(c, units, master, year, cyc, live=None)
        ed = edition_for(snap.year, snap.month)
        wk = idm[idm.week <= pd.Timestamp(snap)]
        idm_wk = wk[wk.week == wk.week.max()].set_index("dist_lgd") if len(wk) and wk.week.max() >= pd.Timestamp(snap) - pd.Timedelta(days=7) else idm.iloc[:0].set_index("dist_lgd")
        idm_cls = idm_wk.cls
        idm_cdi = idm_wk.cdi_mean.astype(float).round(2)  # float32 in the parquet
        idm_d0p = idm_wk[["pct_d0", "pct_d1", "pct_d2", "pct_d3", "pct_d4"]].astype(float).sum(axis=1).round(1)
        # rain: one window for non-NE and one for NE districts
        dep_by_window = {}
        for is_ne in (False, True):
            season, s0, s1 = season_window(snap, is_ne)
            ym0, ym1 = s0.year * 12 + s0.month - 1, s1.year * 12 + s1.month - 1
            x = mon[(mon.ym >= ym0) & (mon.ym <= ym1)]
            complete = x.groupby("dist_lgd").ym.nunique() == (ym1 - ym0 + 1)
            act = x.groupby("dist_lgd").mm.sum(min_count=1).where(complete)
            nrm = normal_sum(normals, s0, s1)
            dep_by_window[is_ne] = (season, s0, s1, ((act - nrm) / nrm * 100).round(), official.get((str(s0), str(s1)), {}),
                                    ri.dry_spells(weekly, wnormal, s0, s1), ri.season_spi(mon, s0, s1))
        for m in master.itertuples():
            code = int(m.dist_lgd)
            season, s0, s1, dep, off, spells, sspi = dep_by_window[code in ne]
            if code in off:
                d, cat, src = off[code][0], off[code][1], "IMD"
            else:
                d = dep.get(code, np.nan)
                d = None if pd.isna(d) else float(d)
                cat, src = (category(d), "gridded") if d is not None else (None, None)
            spi_v = None if code not in sspi else round(float(sspi[code]), 2)
            dry_w = None if code not in spells else int(spells[code])
            short, why = ri.rain_short(cat, spi_v, dry_w)
            r = {"category": cat, "season_days": (s1 - s0).days + 1, "short": short}
            rs, _ = rain_short(r)
            gl, _ = gw_low(g.get(code, {}))
            rows.append({"snapshot": snap, "year": year, "cycle": cyc, "dist_lgd": code,
                         "quadrant": quadrant(rs, gl), "rain_season": season, "rain_window": f"{s0}..{s1}",
                         "rain_category": cat, "rain_dep_pct": d, "rain_source": src,
                         "rain_spi_season": spi_v, "rain_dry_spell_weeks": dry_w, "rain_short": rs,
                         "rain_short_reasons": ",".join(why),
                         "gw_tier": g[code]["tier"], "gw_percentile": g[code].get("percentile"),
                         "gw_median_depth_m": g[code].get("median_depth_m"),
                         "gw_change_vs_ly_m": g[code].get("change_vs_last_year_m"),
                         "gw_vs_10y_m": g[code].get("vs_decadal_mean_m"),
                         "gw_wells": g[code].get("n_wells_with_reading"),
                         "idm_class": idm_cls.get(code) if code in idm_cls.index else None,
                         "idm_cdi_mean": float(idm_cdi[code]) if code in idm_cdi.index and pd.notna(idm_cdi[code]) else None,
                         "idm_d0plus_pct": float(idm_d0p[code]) if code in idm_d0p.index and pd.notna(idm_cls.get(code)) else None,
                         "stress_edition": ed,
                         "stress_category": eds.category.get((ed, code)) if ed else None,
                         "stress_stage_pct": eds.stage_pct.get((ed, code)) if ed else None})
        log.info("%s: %s", snap, pd.Series([r["quadrant"] for r in rows[-len(master):]]).value_counts().to_dict())
    return pd.DataFrame(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=START_YEAR)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    df = build(a.start, pd.Timestamp.today().normalize())
    PROC.mkdir(parents=True, exist_ok=True)
    df.to_csv(PROC / "status_history.csv", index=False)

    snaps = sorted(df.snapshot.astype(str).unique())
    fields = ["quadrant", "rain_category", "rain_dep_pct", "rain_source", "rain_short_reasons",
              "rain_dry_spell_weeks", "rain_spi_season", "gw_tier", "gw_percentile", "idm_class",
              "stress_edition", "stress_category", "stress_stage_pct",
              "gw_median_depth_m", "gw_change_vs_ly_m", "gw_vs_10y_m", "gw_wells", "idm_cdi_mean", "idm_d0plus_pct"]

    def row(r):
        return [(QCODE.get(r["quadrant"]) if pd.notna(r["quadrant"]) else None) if f == "quadrant"
                else (None if pd.isna(r[f]) or r[f] == "" else r[f]) for f in fields]

    hdir = WEB / "history"
    hdir.mkdir(parents=True, exist_ok=True)
    for old in hdir.glob("*.json"):
        old.unlink()
    df = df.assign(snapshot=df.snapshot.astype(str))
    counts = {}
    for snap, g in df.groupby("snapshot"):
        recs = {int(r["dist_lgd"]): row(r) for _, r in g.iterrows()}
        counts[snap] = int(g.quadrant.notna().sum())
        (hdir / f"s_{snap}.json").write_text(webjson.dumps({"snapshot": snap, "fields": fields, "districts": recs},
                                                        separators=(",", ":"), default=str))
    for code, g in df.sort_values("snapshot").groupby("dist_lgd"):
        (hdir / f"d_{int(code)}.json").write_text(webjson.dumps(
            {"fields": ["snapshot"] + fields, "rows": [[r["snapshot"]] + row(r) for _, r in g.iterrows()]},
            separators=(",", ":"), default=str))
    # first snapshot each late-starting layer has data for; the site offers only dates from then on
    layer_from = {}
    for layer, col in (("stress", "stress_edition"), ("idm", "idm_class")):
        has = df[df[col].notna() & (df[col] != "")]
        layer_from[layer] = has.snapshot.min() if len(has) else None
    (hdir / "index.json").write_text(webjson.dumps({
        "snapshots": snaps, "classified": counts, "fields": fields, "layer_from": layer_from,
        "quadrant_codes": {v: k for k, v in QCODE.items() if v},
        "notes": "Rain: IMD official where archived for the exact window, else IMD gridded (district area mean). "
                 "Groundwater: CGWB via NWDP, same-cycle percentile (tiers full/short/provisional)."}, separators=(",", ":")))
    old = WEB / "status_history.json"
    if old.exists():
        old.unlink()
    per = df.groupby("snapshot").quadrant.apply(lambda s: int(s.notna().sum()))
    log.info("snapshots: %d; classified per snapshot min %d / median %d / max %d", len(snaps), per.min(), int(per.median()), per.max())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
