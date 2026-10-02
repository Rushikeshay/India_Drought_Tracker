"""Row-level trace: follow real rows from raw files to the published status, recomputing
each step independently (simple, separate code; no pipeline helpers for the step being
checked) and comparing with what the pipeline produced.

Districts: Sikar (LGD 114; every layer incl. groundwater percentile) and Beed (LGD 470;
IMD official rain).

Each check returns {layer, step, independent, pipeline, ok}. Run as a report:
    python -m pipeline.validate.trace          -> notebooks/phase6b/trace_report.md
and as a test (tests/test_trace.py). Checks whose raw files aren't present locally are skipped.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer
from shapely.geometry import box
from shapely.ops import transform

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
PROC = REPO / "data" / "processed"
REF = REPO / "data" / "reference"
WEB = REPO / "web" / "data"
SIKAR, BEED = 114, 470
TO_EA = Transformer.from_crs(4326, "+proj=aea +lat_1=12 +lat_2=28 +lat_0=20 +lon_0=78 +datum=WGS84 +units=m",
                             always_xy=True).transform


def _poly(code: int):
    d = gpd.read_parquet(REF / "districts.parquet")
    return d.loc[d.dist_lgd == code, "geometry"].iloc[0]


def _check(layer, step, indep, pipe, tol=0.0, rel=False):
    if indep is None or pipe is None:
        ok = indep is None and pipe is None
    elif isinstance(indep, (int, float)) and isinstance(pipe, (int, float)):
        err = abs(indep - pipe) / (abs(indep) if rel and indep else 1)
        ok = err <= tol
    else:
        ok = indep == pipe
    return {"layer": layer, "step": step, "independent": indep, "pipeline": pipe, "ok": bool(ok)}


def _area_weights(poly, centres: list[tuple[float, float]], half: float) -> dict[int, float]:
    """Overlap area (km2) of square cells (lat, lon centres) with poly, by direct intersection."""
    pe = transform(TO_EA, poly)
    minx, miny, maxx, maxy = poly.bounds
    out = {}
    for k, (la, lo) in enumerate(centres):
        if lo + half < minx or lo - half > maxx or la + half < miny or la - half > maxy:
            continue
        a = transform(TO_EA, box(float(lo) - half, float(la) - half, float(lo) + half, float(la) + half)).intersection(pe).area / 1e6
        if a > 0.01:
            out[k] = a
    return out


# ---------------- rain ----------------

def rain_checks() -> list[dict]:
    out = []
    poly = _poly(SIKAR)
    lats, lons = 6.5 + 0.25 * np.arange(129), 66.5 + 0.25 * np.arange(135)
    centres = [(la, lo) for la in lats for lo in lons]
    w = _area_weights(poly, centres, 0.125)

    daily = pd.read_parquet(PROC / "rain_current_daily.parquet")
    daily["date"] = pd.to_datetime(daily.date)
    # 1. one raw real-time grid -> district value
    f = RAW / "imd" / "realtime" / "rain_ind0.25_26_08_15.grd"
    if f.exists():
        raw = np.frombuffer(f.read_bytes(), dtype="<f4").reshape(129, 135).ravel()
        num = sum(wt * raw[k] for k, wt in w.items() if raw[k] > -998)
        den = sum(wt for k, wt in w.items() if raw[k] > -998)
        pipe = daily[(daily.date == "2026-08-15") & (daily.dist_lgd == SIKAR)].mm.iloc[0]
        out.append(_check("rain", "raw IMD grid 2026-08-15 -> Sikar area mean (mm)", round(float(num / den), 3), round(float(pipe), 3), 0.01))
    # 2. one raw yearly grid day -> reduced history value
    f = RAW / "imd" / "yearly" / "Rainfall_ind2025_rfp25.grd"
    r = RAW / "imd" / "reduced" / "2025.parquet"
    if f.exists() and r.exists():
        raw = np.frombuffer(f.read_bytes(), dtype="<f4").reshape(-1, 129, 135)[pd.Timestamp("2025-07-20").dayofyear - 1].ravel()
        num = sum(wt * raw[k] for k, wt in w.items() if raw[k] > -998)
        den = sum(wt for k, wt in w.items() if raw[k] > -998)
        pipe = pd.read_parquet(r).loc[pd.Timestamp("2025-07-20"), str(SIKAR)]
        out.append(_check("rain", "raw IMD yearly grid 2025-07-20 -> Sikar (mm)", round(float(num / den), 3), round(float(pipe), 3), 0.01))
    # 3. normal Jun1-Sep30 = mean over 1971-2020 of seasonal sums
    red = RAW / "imd" / "reduced"
    if all((red / f"{y}.parquet").exists() for y in range(1971, 2021)):
        sums = [pd.read_parquet(red / f"{y}.parquet").loc[f"{y}-06-01":f"{y}-09-30", str(SIKAR)].sum() for y in range(1971, 2021)]
        n = pd.read_parquet(PROC / "rain_daily_normal.parquet")
        n = n[(n.dist_lgd == SIKAR) & n.month.between(6, 9)].mm.sum()
        out.append(_check("rain", "1971-2020 normal Jun-Sep, Sikar (mm)", round(float(np.mean(sums)), 1), round(float(n), 1), 0.2))
    # 4. season actual + departure (gridded) -> rain.json
    rj = json.loads((WEB / "rain.json").read_text())["districts"][str(SIKAR)]
    act = daily[(daily.dist_lgd == SIKAR) & daily.date.between("2026-06-01", "2026-09-30")].mm.sum()
    out.append(_check("rain", "gridded Jun-Sep 2026 actual, Sikar (mm)", round(float(act), 1), rj["gridded"]["actual_mm"], 0.15))
    dep = (rj["gridded"]["actual_mm"] - rj["gridded"]["normal_mm"]) / rj["gridded"]["normal_mm"] * 100
    out.append(_check("rain", "gridded departure % = (actual-normal)/normal", round(dep), rj["gridded"]["departure_pct"], 1))
    # 5. IMD official: raw PDF line -> archived season file -> rain.json headline
    pdf = RAW / "imd" / "validation" / "DISTRICT_RAINFALL_DEPARTURECUMULATIVE_COUNTRY_INDIA_c.pdf"
    if pdf.exists():
        from pypdf import PdfReader
        text = "\n".join(p.extract_text() for p in PdfReader(pdf).pages)
        season = pd.read_csv(PROC / "imd_official" / "season_2026_SW.csv")
        for code, name in ((SIKAR, "SIKAR"), (BEED, "BEED")):
            m = re.search(rf"(?m)^\d+\s+{name}\s+((?:-?\d+\s+)*-?\d+)\s*$", text)
            raw_last = int(m.group(1).split()[-1])
            arch = int(season.loc[season.dist_lgd == code, "period_dep_pct"].iloc[0])
            head = json.loads((WEB / "rain.json").read_text())["districts"][str(code)]
            out.append(_check("rain", f"IMD PDF '{name}' last column -> season_2026_SW.csv", raw_last, arch))
            out.append(_check("rain", f"season_2026_SW.csv -> rain.json headline ({name}, source {head['source']})", arch, head["departure_pct"]))
    return out


# ---------------- groundwater ----------------

def _raw_tele_rows(station: str, lat: float, lon: float) -> pd.DataFrame:
    rows = []
    for p in sorted((RAW / "nwdp" / "telemetry").glob("*_rj_*.csv")):
        d = pd.read_csv(p, low_memory=False)
        val = next(c for c in d.columns if c.startswith("Groundwater Level"))
        d = d[(d.Station == station) & (d.Latitude.round(4) == round(lat, 4)) & (d.Longitude.round(4) == round(lon, 4))]
        rows.append(d.assign(v=pd.to_numeric(d[val], errors="coerce"),
                             t=pd.to_datetime(d["Data Acquisition Time"], format="%d-%m-%Y %H:%M")))
    return pd.concat(rows)


def gw_checks() -> list[dict]:
    out = []
    cyc = pd.read_parquet(PROC / "gw_cycles.parquet")
    # 1. raw telemetry rows -> Aug 2026 cycle value (sign from the well's own median)
    if any((RAW / "nwdp" / "telemetry").glob("*_rj_*.csv")):
        r = _raw_tele_rows("Khatu Shyamji_1", 27.3667, 75.4)
        sign = -1 if r.v.median() < 0 else 1
        aug = r[(r.t.dt.year == 2026) & (r.t.dt.month == 8)].v.median() * sign
        pipe = cyc[(cyc.well_id == "t:27.3667,75.4000:khatu shyamji") & (cyc.year == 2026) & (cyc.cycle == "AUG")].depth_m.iloc[0]
        out.append(_check("groundwater", "raw telemetry 'Khatu Shyamji_1' Aug 2026 median x own sign (m)", round(float(aug), 3), round(float(pipe), 3), 0.001))
    # 2. raw manual rows -> Nov 2015 cycle value for a Sikar manual well
    w = pd.read_parquet(PROC / "gw_wells.parquet")
    mw = w[(w.dist_lgd == SIKAR) & (w.source == "manual")]
    mc = cyc[cyc.well_id.isin(mw.well_id) & (cyc.year == 2015) & (cyc.cycle == "NOV")]
    if len(mc) and any((RAW / "nwdp" / "manual").glob("*_rj_*.csv")):
        wid = mc.well_id.iloc[0]
        lat, lon = map(float, wid.split(":")[1].split(","))
        vals = []
        for p in (RAW / "nwdp" / "manual").glob("*_rj_*.csv"):
            d = pd.read_csv(p, low_memory=False)
            val = next(c for c in d.columns if c.startswith("Groundwater Level"))
            d = d[(d.Latitude.round(4) == round(lat, 4)) & (d.Longitude.round(4) == round(lon, 4))]
            t = pd.to_datetime(d["Data Acquisition Time"], format="%d-%m-%Y %H:%M")
            d = d[(t.dt.year == 2015) & t.dt.month.isin([10, 11])]
            d = d[d.Station.str.replace(r"_\d+$", "", regex=True).str.strip().str.lower() == wid.split(":", 2)[2]]
            vals += pd.to_numeric(d[val], errors="coerce").dropna().tolist()
        out.append(_check("groundwater", f"raw manual '{wid}' Nov 2015 (m)", round(float(np.median(vals)), 3), round(float(mc.depth_m.iloc[0]), 3), 0.001))
    # 3. district percentile, recomputed with plain loops from the series
    from pipeline.process.groundwater import series
    c, units = series()
    su = set(units[units.dist_lgd == SIKAR].index)
    s = c[c.unit.isin(su) & (c.cycle == "AUG")]
    pcts = []
    for u, g in s.groupby("unit"):
        now = g[g.year == 2026].depth_m
        hist = g[g.year < 2026].depth_m.tolist()
        if len(now) and len(hist) >= 10:
            x = now.iloc[0]
            deeper = sum(1 for h in hist if h > x) + 0.5 * sum(1 for h in hist if h == x)
            pcts.append(100 * deeper / len(hist))
    gj = json.loads((WEB / "groundwater.json").read_text())["districts"][str(SIKAR)]
    out.append(_check("groundwater", "wells with >= 10 Aug years and an Aug 2026 reading", len(pcts), gj.get("n_wells_used")))
    out.append(_check("groundwater", "median of per-well percentiles (Aug 2026)", round(float(np.median(pcts))), gj.get("percentile")))
    out.append(_check("groundwater", "low = percentile <= 20", bool(np.median(pcts) <= 20), gj.get("low")))
    return out


# ---------------- IN-GRES ----------------

def stress_checks() -> list[dict]:
    out = []
    raw = RAW / "ingres" / "2025-2026"
    sj = json.loads((WEB / "stress.json").read_text())["districts"][str(SIKAR)]
    st = raw / "state_RAJASTHAN.json"
    if st.exists():
        row = next(r for r in json.loads(st.read_text()) if (r.get("locationName") or "").upper() == "SIKAR")
        out.append(_check("stress", "raw IN-GRES stageOfExtraction.total, Sikar (%)", round(row["stageOfExtraction"]["total"], 2), sj["stage_pct"], 0.01))
        out.append(_check("stress", "raw IN-GRES category.total", row["category"]["total"], {"Over-exploited": "over_exploited"}.get(sj["category"], sj["category"])))
    units = list(raw.glob("district_RAJASTHAN_SIKAR*.json"))
    if units:
        rows = [r for r in json.loads(units[0].read_text()) if r.get("locationUUID") and (r.get("locationName") or "").lower() != "total"]
        rank = {"safe": 0, "semi_critical": 1, "critical": 2, "over_exploited": 3}
        best = max(rows, key=lambda r: (rank.get(r["category"]["total"], -1), r["stageOfExtraction"]["total"] or -1))
        out.append(_check("stress", "worst unit = highest category, then highest stage", best["locationName"], sj["worst_unit"]["name"]))
        out.append(_check("stress", "number of units", len(rows), sj["units"]["n"]))
    return out


# ---------------- IDM ----------------

def idm_checks() -> list[dict]:
    f = RAW / "idm" / "CDI_20260930.txt"
    if not f.exists():
        return []
    g = pd.read_csv(f, sep=r"\s+", header=None, names=["lat", "lon", "cdi"]).dropna(subset=["lat", "lon"]).reset_index(drop=True)
    w = _area_weights(_poly(SIKAR), list(zip(g.lat, g.lon)), 0.125)
    v = g.cdi.to_numpy()
    valid = {k: a for k, a in w.items() if not np.isnan(v[k])}
    tot = sum(valid.values())
    mean = sum(a * v[k] for k, a in valid.items()) / tot
    d1p = 100 * sum(a for k, a in valid.items() if v[k] <= -0.8) / tot
    ij = json.loads((WEB / "idm.json").read_text())["districts"][str(SIKAR)]
    pipe_d1p = sum(ij["pct"][c] for c in ("d1", "d2", "d3", "d4"))
    return [_check("idm", "raw CDI 2026-09-30 -> Sikar area-weighted mean", round(mean, 2), ij["cdi_mean"], 0.011),
            _check("idm", "share of Sikar area at D1 or worse (%)", round(d1p, 1), round(pipe_d1p, 1), 0.3)]


# ---------------- classification + history ----------------

def classify_checks() -> list[dict]:
    st = json.loads((WEB / "status.json").read_text())["districts"][str(SIKAR)]
    rain_short = st["rain"]["category"] in ("Deficient", "Large Deficient", "No Rain")
    gw_low = st["gw"]["percentile"] <= 20
    q = {(False, False): "fine", (False, True): "hidden_drought", (True, False): "buffered", (True, True): "double_drought"}[(rain_short, gw_low)]
    out = [_check("classify", f"rain {st['rain']['category']} + GW pct {st['gw']['percentile']} -> quadrant", q, st["quadrant"])]
    h = pd.read_csv(PROC / "status_history.csv", low_memory=False)
    h = h[(h.dist_lgd == SIKAR) & (h.snapshot == "2026-08-31")].iloc[0]
    gj = json.loads((WEB / "groundwater.json").read_text())
    if gj["cycle"] == "AUG" and gj["cycle_year"] == 2026:
        out.append(_check("history", "2026-08-31 snapshot GW percentile = current Aug 2026", gj["districts"][str(SIKAR)]["percentile"], int(h.gw_percentile)))
    daily = pd.read_parquet(PROC / "rain_current_daily.parquet")
    daily["date"] = pd.to_datetime(daily.date)
    act = daily[(daily.dist_lgd == SIKAR) & daily.date.between("2026-06-01", "2026-08-31")].mm.sum()
    n = pd.read_parquet(PROC / "rain_daily_normal.parquet")
    nrm = n[(n.dist_lgd == SIKAR) & n.month.between(6, 8)].mm.sum()
    out.append(_check("history", "2026-08-31 snapshot rain departure (Jun-Aug, gridded)", round((act - nrm) / nrm * 100), h.rain_dep_pct, 1))
    return out


def run() -> list[dict]:
    return rain_checks() + gw_checks() + stress_checks() + idm_checks() + classify_checks()


def main() -> int:
    res = run()
    lines = ["# Row-level trace report", "", f"Generated {date.today()}. Districts: Sikar (114), Beed (470).", "",
             "| Layer | Step | Independent | Pipeline | OK |", "|---|---|---|---|---|"]
    lines += [f"| {r['layer']} | {r['step']} | {r['independent']} | {r['pipeline']} | {'✅' if r['ok'] else '❌'} |" for r in res]
    out = REPO / "notebooks" / "phase6b"
    out.mkdir(parents=True, exist_ok=True)
    (out / "trace_report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if all(r["ok"] for r in res) else 1


if __name__ == "__main__":
    raise SystemExit(main())
