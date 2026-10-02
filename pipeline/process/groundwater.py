"""Phase 3: CGWB groundwater levels (NWDP) -> well cycles -> district status.

Stage 1 (`cycles`): every manual and telemetry reading -> one value per well per
standard cycle per year:
    JAN = Dec-Feb, PRE (pre-monsoon) = Mar-Jun, AUG = Jul-Sep, NOV = Oct-Nov
Manual readings fall in Jan, Apr-May, Aug and Nov (checked). Telemetry is reduced
to the median of its readings in the matching campaign months (Jan, Apr-May, Aug,
Nov), so both sources describe the same moment of the year.

Well identity = location (lat/lon to 4 dp) + station base name (trailing "_1"
removed). Location alone is not enough: 1,932 coordinates carry several wells
(nested piezometers, replacements).

Signs: manual values are depth below ground (positive down). Telemetry is mostly
negative down. Each telemetry well's sign is set from the median of its own
readings; values are never abs()'d. After normalising, depths outside
ENVELOPE_M are dropped and counted (data/processed/gw_dropped.json).

Outputs
  data/processed/gw_cycles.parquet   well_id, source, station, lat, lon, year, cycle, depth_m, n
  data/processed/gw_wells.parquet    one row per well: source, station, lat, lon, dist_lgd,
                                     first/last reading, sign used
  data/processed/gw_tele_latest.parquet  per telemetry well: last reading time, median of last 30 days

Stage 2 (`pairs`): telemetry well <-> manual well at the same site (<= PAIR_MAX_M),
accepted only when >= PAIR_MIN_OVERLAP shared cycles agree within PAIR_MAX_DIFF_M
(median |difference|). Co-located wells are often different piezometers.
  -> data/processed/gw_pairs.csv

Stage 3 (`status`): district status for the latest completed cycle (current tier)
and long-term trends/anomalies (historical tier).
  -> web/data/groundwater.json, web/data/gw_history.json

Usage: python -m pipeline.process.groundwater [cycles|pairs|status|all]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw" / "nwdp"
PROC = REPO / "data" / "processed"
REF = REPO / "data" / "reference"
TIME_FMT = "%d-%m-%Y %H:%M"
ENVELOPE_M = (-5.0, 150.0)
CYCLE_OF_MONTH = {12: "JAN", 1: "JAN", 2: "JAN", 3: "PRE", 4: "PRE", 5: "PRE", 6: "PRE",
                  7: "AUG", 8: "AUG", 9: "AUG", 10: "NOV", 11: "NOV"}
TELE_CAMPAIGN_MONTHS = {1: "JAN", 4: "PRE", 5: "PRE", 8: "AUG", 11: "NOV"}
PAIR_MAX_M = 50
PAIR_MIN_OVERLAP = 2
PAIR_MAX_DIFF_M = 1.5
CYCLE_END = {"JAN": (1, 31), "PRE": (5, 31), "AUG": (8, 31), "NOV": (11, 30)}
CYCLES = ["JAN", "PRE", "AUG", "NOV"]
LIVE_DAYS = 60
TIERS = [("full", 5, 10), ("short", 3, 5)]  # (name, min wells, min same-cycle history years)
LOW_PCT = 20
MAX_JUMP_M = 10  # |change vs same cycle last year| above this: flagged for review (kept; medians limit influence)
BASELINE = (2000, 2023)
WEB = REPO / "web" / "data"
COLS = ["Station", "Agency", "Latitude", "Longitude", "Data Acquisition Time"]

log = logging.getLogger("groundwater")


def _base(name: pd.Series) -> pd.Series:
    return name.astype(str).str.replace(r"_\d+$", "", regex=True).str.strip().str.lower()


def _well_id(source: str, lat: pd.Series, lon: pd.Series, station: pd.Series) -> pd.Series:
    return source[0] + ":" + lat.round(4).map("{:.4f}".format) + "," + lon.round(4).map("{:.4f}".format) + ":" + _base(station)


def _read(path: Path, chunksize: int | None = None):
    head = pd.read_csv(path, nrows=0).columns
    val = next(c for c in head if c.startswith("Groundwater Level"))
    return pd.read_csv(path, usecols=COLS + [val], chunksize=chunksize, low_memory=False,
                       dtype={"Station": str, "Agency": str}), val


def _prep(d: pd.DataFrame, val: str) -> pd.DataFrame:
    d = d.rename(columns={val: "v"})
    d["t"] = pd.to_datetime(d["Data Acquisition Time"], format=TIME_FMT, errors="coerce")
    for c in ("Latitude", "Longitude", "v"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    return d.dropna(subset=["t", "Latitude", "Longitude", "v"])


def manual_cycles() -> pd.DataFrame:
    parts = []
    for p in sorted((RAW / "manual").glob("*.csv")):
        d, val = _read(p)
        d = _prep(d, val)
        if d.empty:
            continue
        d["year"] = d.t.dt.year + (d.t.dt.month == 12)  # December reading belongs to the next January cycle
        d["cycle"] = d.t.dt.month.map(CYCLE_OF_MONTH)
        d["well_id"] = _well_id("manual", d.Latitude, d.Longitude, d.Station)
        parts.append(d)
    m = pd.concat(parts, ignore_index=True)
    g = m.groupby(["well_id", "year", "cycle"])
    out = g.agg(station=("Station", "last"), agency=("Agency", "last"), lat=("Latitude", "last"),
                lon=("Longitude", "last"), raw=("v", "median"), n=("v", "size"), last=("t", "max")).reset_index()
    out["source"] = "manual"
    return out


def tele_cycles() -> tuple[pd.DataFrame, pd.DataFrame]:
    parts, latest = [], []
    for p in sorted((RAW / "telemetry").glob("*.csv")):
        reader, val = _read(p, chunksize=2_000_000)
        for d in reader:
            d = _prep(d, val)
            if d.empty:
                continue
            d["well_id"] = _well_id("tele", d.Latitude, d.Longitude, d.Station)
            latest.append(d.groupby("well_id").agg(last=("t", "max")).reset_index())
            # keep the last 45 days of every well for the "latest level" value
            recent = d[d.t >= d.groupby("well_id").t.transform("max") - pd.Timedelta(days=45)]
            latest.append(recent[["well_id", "t", "v"]])
            c = d[d.t.dt.month.isin(TELE_CAMPAIGN_MONTHS)]
            c = c.assign(year=c.t.dt.year, cycle=c.t.dt.month.map(TELE_CAMPAIGN_MONTHS))
            parts.append(c.groupby(["well_id", "year", "cycle"]).agg(
                station=("Station", "last"), agency=("Agency", "last"), lat=("Latitude", "last"),
                lon=("Longitude", "last"), raw=("v", "median"), n=("v", "size"), last=("t", "max")).reset_index())
        log.info("telemetry %s done", p.name)
    t = pd.concat(parts, ignore_index=True)
    # a cycle can be split across chunks/files: recombine (median of medians, weighted enough for 6-hourly data)
    t = t.groupby(["well_id", "year", "cycle"]).agg(
        station=("station", "last"), agency=("agency", "last"), lat=("lat", "last"), lon=("lon", "last"),
        raw=("raw", "median"), n=("n", "sum"), last=("last", "max")).reset_index()
    t["source"] = "tele"
    lat = pd.concat([x for x in latest if "v" in x.columns], ignore_index=True)
    last_t = pd.concat([x for x in latest if "v" not in x.columns]).groupby("well_id")["last"].max()
    lat = lat[lat.t >= lat.well_id.map(last_t) - pd.Timedelta(days=30)]
    lt = lat.groupby("well_id").agg(last=("t", "max"), raw_30d=("v", "median"), n_30d=("v", "size")).reset_index()
    return t, lt


def assign_signs(c: pd.DataFrame) -> pd.Series:
    """+1 where values are positive-down already, -1 where the well reports negative-down."""
    med = c.groupby("well_id").raw.median()
    sign = pd.Series(1, index=med.index)
    tele = med.index.str.startswith("t:")
    sign[tele & (med < 0)] = -1
    return sign


def build_cycles() -> None:
    m = manual_cycles()
    log.info("manual: %d well-cycles, %d wells", len(m), m.well_id.nunique())
    t, latest = tele_cycles()
    log.info("telemetry: %d well-cycles, %d wells", len(t), t.well_id.nunique())
    c = pd.concat([m, t], ignore_index=True)
    sign = assign_signs(c)
    c["depth_m"] = c.raw * c.well_id.map(sign)
    lo, hi = ENVELOPE_M
    bad = ~c.depth_m.between(lo, hi)
    dropped = {"envelope_m": ENVELOPE_M, "well_cycles_dropped": int(bad.sum()),
               "by_source": c[bad].source.value_counts().to_dict(),
               "examples": c[bad].nlargest(5, "depth_m")[["station", "depth_m"]].to_dict("records")}
    log.info("dropped %d well-cycles outside %s m", bad.sum(), ENVELOPE_M)
    c = c[~bad]

    wells = c.groupby("well_id").agg(source=("source", "first"), station=("station", "last"),
                                     agency=("agency", "last"), lat=("lat", "last"), lon=("lon", "last"),
                                     first_year=("year", "min"), last=("last", "max")).reset_index()
    wells["sign"] = wells.well_id.map(sign)
    d = gpd.read_parquet(REF / "districts.parquet")[["dist_lgd", "geometry"]]
    g = gpd.GeoDataFrame(wells, geometry=gpd.points_from_xy(wells.lon, wells.lat), crs=4326)
    j = gpd.sjoin(g, d, how="left", predicate="within")
    wells["dist_lgd"] = j.groupby(level=0).dist_lgd.first().reindex(wells.index).astype("Int64")
    dropped["wells_outside_districts"] = int(wells.dist_lgd.isna().sum())

    latest["depth_30d"] = latest.raw_30d * latest.well_id.map(sign).fillna(1)
    PROC.mkdir(parents=True, exist_ok=True)
    c[["well_id", "source", "year", "cycle", "depth_m", "n"]].astype({"year": "int16", "n": "int32"}).to_parquet(
        PROC / "gw_cycles.parquet", index=False)
    wells.to_parquet(PROC / "gw_wells.parquet", index=False)
    latest.to_parquet(PROC / "gw_tele_latest.parquet", index=False)
    (PROC / "gw_dropped.json").write_text(json.dumps(dropped, indent=2, default=str))
    log.info("wells: %d (%d outside district polygons)", len(wells), dropped["wells_outside_districts"])


# ---------------- stage 2: pairing ----------------

def build_pairs() -> pd.DataFrame:
    c = pd.read_parquet(PROC / "gw_cycles.parquet")
    w = pd.read_parquet(PROC / "gw_wells.parquet")
    tw = w[w.source == "tele"].reset_index(drop=True)
    mw = w[w.source == "manual"].reset_index(drop=True)
    ml = np.radians(mw[["lat", "lon"]].to_numpy(float))
    rows = []
    for r, (la, lo) in zip(tw.itertuples(), np.radians(tw[["lat", "lon"]].to_numpy(float))):
        dd = np.hypot((ml[:, 1] - lo) * np.cos(la), ml[:, 0] - la) * 6_371_000
        for i in np.flatnonzero(dd <= PAIR_MAX_M):
            rows.append({"tele_id": r.well_id, "manual_id": mw.well_id.iloc[i], "dist_m": round(float(dd[i]), 1)})
    cand = pd.DataFrame(rows)
    t = c[c.source == "tele"].rename(columns={"well_id": "tele_id", "depth_m": "td"})[["tele_id", "year", "cycle", "td"]]
    m = c[c.source == "manual"].rename(columns={"well_id": "manual_id", "depth_m": "md"})[["manual_id", "year", "cycle", "md"]]
    j = cand.merge(t, on="tele_id").merge(m, on=["manual_id", "year", "cycle"])
    j["d"] = j.td - j.md
    s = j.groupby(["tele_id", "manual_id"]).agg(n_overlap=("d", "size"), med_abs_diff=("d", lambda x: x.abs().median()),
                                                bias=("d", "median")).reset_index()
    s = s.merge(cand, on=["tele_id", "manual_id"])
    s["accepted"] = (s.n_overlap >= PAIR_MIN_OVERLAP) & (s.med_abs_diff <= PAIR_MAX_DIFF_M)
    # one manual partner per telemetry well (and vice versa): best agreement wins
    acc = s[s.accepted].sort_values("med_abs_diff")
    acc = acc.drop_duplicates("tele_id").drop_duplicates("manual_id")
    s["accepted"] = s.set_index(["tele_id", "manual_id"]).index.isin(acc.set_index(["tele_id", "manual_id"]).index)
    s.round(3).to_csv(PROC / "gw_pairs.csv", index=False)
    log.info("pairs: %d candidates with overlap, %d accepted", len(s), int(s.accepted.sum()))
    return s


def series() -> tuple[pd.DataFrame, pd.DataFrame]:
    """One depth series per analysis well. A telemetry well with an accepted manual
    partner gets the partner's readings for (year, cycle)s it lacks; the partner is
    then not used separately."""
    c = pd.read_parquet(PROC / "gw_cycles.parquet")
    w = pd.read_parquet(PROC / "gw_wells.parquet").set_index("well_id")
    pairs = pd.read_csv(PROC / "gw_pairs.csv")
    pairs = pairs[pairs.accepted]
    alias = dict(zip(pairs.manual_id, pairs.tele_id))
    c["unit"] = c.well_id.map(alias).fillna(c.well_id)
    # prefer the telemetry value where both exist
    c = c.sort_values("source", ascending=False).drop_duplicates(["unit", "year", "cycle"])
    units = w.loc[w.index.isin(c.unit.unique())].copy()
    units["paired_manual"] = units.index.map({v: k for k, v in alias.items()})
    return c, units


# ---------------- stage 3: status ----------------

def current_cycle(today: pd.Timestamp) -> tuple[int, str]:
    """Latest standard cycle whose campaign window has ended."""
    best = None
    for y in (today.year - 1, today.year):
        for cyc in CYCLES:
            m, d = CYCLE_END[cyc]
            if pd.Timestamp(y, m, d) < today:
                best = (y, cyc)
    return best


def percentile_low(hist: np.ndarray, x: float) -> float:
    """Share (0-100) of past same-cycle years with water DEEPER than now. 0 = deepest on record."""
    return float(100 * (np.sum(hist > x) + 0.5 * np.sum(hist == x)) / len(hist))


def sen_slope(years: np.ndarray, vals: np.ndarray) -> float:
    i, j = np.triu_indices(len(years), 1)
    dy = years[j] - years[i]
    ok = dy != 0
    return float(np.median((vals[j] - vals[i])[ok] / dy[ok]))


def district_status(c: pd.DataFrame, units: pd.DataFrame, master: pd.DataFrame, year: int, cyc: str,
                    live: set | None = None) -> tuple[dict, int]:
    """Per-district groundwater status for one (year, cycle). `live`: wells counted as
    live for the level_only tier (None = every well with a reading in that cycle)."""
    cur = c[(c.year == year) & (c.cycle == cyc)].set_index("unit").depth_m
    same = c[(c.cycle == cyc) & (c.year < year)]
    hist = same.groupby("unit").depth_m.apply(np.asarray)
    dec = same[same.year >= year - 10].groupby("unit").depth_m.agg(["mean", "size"])
    wells = []
    for u, x in cur.items():
        h = hist.get(u, np.array([]))
        wells.append({
            "unit": u, "dist_lgd": units.loc[u, "dist_lgd"] if u in units.index else pd.NA, "depth_m": x,
            "hist_years": len(h), "pct": percentile_low(h, x) if len(h) else np.nan,
            "vs_decadal_mean_m": (dec.loc[u, "mean"] - x) if u in dec.index and dec.loc[u, "size"] >= 5 else np.nan,
            "live": True if live is None else u in live,
        })
    W = pd.DataFrame(wells, columns=["unit", "dist_lgd", "depth_m", "hist_years", "pct", "vs_decadal_mean_m", "live"])
    W = W.dropna(subset=["dist_lgd"])
    W["dist_lgd"] = W.dist_lgd.astype(int)
    prev = {"JAN": "NOV", "PRE": "JAN", "AUG": "PRE", "NOV": "AUG"}[cyc]
    prev_year = year - 1 if cyc == "JAN" else year
    prev_v = c[(c.year == prev_year) & (c.cycle == prev)].set_index("unit").depth_m
    W["change_since_prev_cycle_m"] = W.unit.map(prev_v) - W.depth_m  # positive = water rose
    ly = c[(c.year == year - 1) & (c.cycle == cyc)].set_index("unit").depth_m
    W["change_vs_last_year_m"] = W.unit.map(ly) - W.depth_m
    W["jump"] = W.change_vs_last_year_m.abs() > MAX_JUMP_M
    n_jump = int(W.jump.sum())

    out = {}
    for code in master.dist_lgd:
        d = W[W.dist_lgd == code]
        rec = {"tier": "insufficient", "n_wells_with_reading": int(len(d)), "n_live": int(d.live.sum()),
               "n_wells_jump_gt_10m": int(d.jump.sum())}
        for name, nmin, ymin in TIERS:
            q = d[d.hist_years >= ymin]
            if len(q) >= nmin:
                p = float(q.pct.median())
                rec.update(tier=name, n_wells_used=int(len(q)), percentile=round(p), low=p <= LOW_PCT,
                           median_hist_years=int(q.hist_years.median()))
                break
        if rec["tier"] == "insufficient" and d.live.any():
            rec["tier"] = "level_only"
        if len(d):
            rec.update(median_depth_m=_r(d.depth_m.median()), vs_decadal_mean_m=_r(d.vs_decadal_mean_m.median()),
                       change_since_prev_cycle_m=_r(d.change_since_prev_cycle_m.median()),
                       change_vs_last_year_m=_r(d.change_vs_last_year_m.median()))
        out[int(code)] = rec
    return out, n_jump


def build_status(today: pd.Timestamp | None = None) -> None:
    today = today or pd.Timestamp.today().normalize()
    year, cyc = current_cycle(today)
    c, units = series()
    master = pd.read_csv(REF / "district_master.csv")
    latest = pd.read_parquet(PROC / "gw_tele_latest.parquet").set_index("well_id")

    # ---- current tier ----
    live_cut = today - pd.Timedelta(days=LIVE_DAYS)
    last_t = latest["last"].combine_first(units["last"])
    live = set(last_t[last_t >= live_cut].index)
    out, n_jump = district_status(c, units, master, year, cyc, live)
    tiers = pd.Series([v["tier"] for v in out.values()]).value_counts().to_dict()
    doc = {"as_of": str(today.date()), "cycle": cyc, "cycle_year": year,
           "cycle_months": {"JAN": "January", "PRE": "pre-monsoon (Apr-May)", "AUG": "August", "NOV": "November"}[cyc],
           "rules": {"low_percentile_max": LOW_PCT, "tiers": {n: f">= {w} wells with >= {y} same-cycle years" for n, w, y in TIERS},
                     "percentile_meaning": "share of past same-cycle years with water deeper than now (0 = deepest on record)",
                     "signs": "change values in metres; positive = water level rose"},
           "source": "CGWB via National Water Data Portal (telemetry + manual quarterly); wells joined to districts by location",
           "tier_counts": tiers, "wells_flagged_jump_gt_10m": n_jump, "districts": out}
    WEB.mkdir(parents=True, exist_ok=True)
    (WEB / "groundwater.json").write_text(json.dumps(doc, separators=(",", ":")))
    log.info("current %s %s: %s", cyc, year, tiers)

    # ---- historical tier ----
    b = c[c.year.between(*BASELINE)]
    clim = b.groupby(["unit", "cycle"]).depth_m.agg(["mean", "size"])
    clim = clim[clim["size"] >= 10]["mean"]
    h = c[c.year.between(BASELINE[0], year)].join(clim.rename("clim"), on=["unit", "cycle"]).dropna(subset=["clim"])
    h["anom"] = h.depth_m - h.clim  # positive = deeper than usual
    h["dist_lgd"] = h.unit.map(units.dist_lgd)
    h = h.dropna(subset=["dist_lgd"]).astype({"dist_lgd": int})
    ser = h[h.cycle.isin(["PRE", "NOV"])].groupby(["dist_lgd", "cycle", "year"]).agg(a=("anom", "median"), n=("anom", "size"))
    pre = b[b.cycle == "PRE"]
    slopes = {}
    for u, g in pre.groupby("unit"):
        if g.year.nunique() >= 10:
            slopes[u] = sen_slope(g.year.to_numpy(float), g.depth_m.to_numpy(float))
    sl = pd.DataFrame({"slope": pd.Series(slopes)})
    sl["dist_lgd"] = sl.index.map(units.dist_lgd)
    sl = sl.dropna(subset=["dist_lgd"]).astype({"dist_lgd": int})
    hist_doc = {"baseline": f"{BASELINE[0]}-{BASELINE[1]}",
                "meaning": "anomaly = district median of each well's depth minus its own baseline mean for that cycle "
                           "(m; positive = deeper than usual). trend = median Sen slope of pre-monsoon depth (m/yr; positive = falling water table)",
                "districts": {}}
    for code in master.dist_lgd:
        rec = {}
        s_ = sl[sl.dist_lgd == code].slope
        if len(s_) >= 3:
            rec["trend_pre_m_per_yr"] = round(float(s_.median()), 3)
            rec["trend_wells"] = int(len(s_))
            rec["share_wells_falling"] = round(float((s_ > 0).mean()), 2)
        for cy in ("PRE", "NOV"):
            if (code, cy) in ser.index.droplevel(2):
                x = ser.loc[(code, cy)]
                x = x[x.n >= 3]
                if len(x):
                    rec[cy] = {str(int(y)): [round(float(r.a), 2), int(r.n)] for y, r in x.iterrows()}
        if rec:
            hist_doc["districts"][int(code)] = rec
    (WEB / "gw_history.json").write_text(json.dumps(hist_doc, separators=(",", ":")))
    log.info("history: %d districts with trend, %d with any series",
             sum("trend_pre_m_per_yr" in v for v in hist_doc["districts"].values()), len(hist_doc["districts"]))


def _r(x, nd=2):
    return None if x is None or pd.isna(x) else round(float(x), nd)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["cycles", "pairs", "status", "all"])
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if a.stage in ("cycles", "all"):
        build_cycles()
    if a.stage in ("pairs", "all"):
        build_pairs()
    if a.stage in ("status", "all"):
        build_status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
