"""Phase 5: IDM Combined Drought Index (CDI) -> districts.

Per district and week: area-weighted mean CDI and the share of the district's
area (cells with data) in each IDM class. Class edges copied from IDM's own code
(build_districts.py classify(), drought-map.colormaps.js):
    Normal > -0.5 >= D0 > -0.8 >= D1 > -1.3 >= D2 > -1.6 >= D3 > -2.0 >= D4
IDM's own district file counts cells; we weight by overlap area with our LGD boundaries.

Outputs
  data/reference/idm_district_weights.csv
  data/processed/idm_weekly.parquet     week, dist_lgd, cdi_mean, pct_none, pct_d0..pct_d4, coverage
  web/data/idm.json                     latest week + change vs 4 weeks ago + last 26 weeks of % in D1+
Usage: python -m pipeline.process.idm
"""

from __future__ import annotations

import json

from pipeline import webjson
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from scipy import sparse

from pipeline.sources import idm

REPO = Path(__file__).resolve().parents[2]
REF = REPO / "data" / "reference"
PROC = REPO / "data" / "processed"
WEB = REPO / "web" / "data"
EQUAL_AREA = "+proj=aea +lat_1=12 +lat_2=28 +lat_0=20 +lon_0=78 +datum=WGS84 +units=m"
EDGES = [-0.5, -0.8, -1.3, -1.6, -2.0]  # upper edges of D0..D4
CLASSES = ["none", "d0", "d1", "d2", "d3", "d4"]
HALF = 0.125

log = logging.getLogger("idm_process")


def classify(v: np.ndarray) -> np.ndarray:
    """Index into CLASSES; -1 for missing."""
    out = np.full(v.shape, -1)
    ok = ~np.isnan(v)
    out[ok & (v > EDGES[0])] = 0
    for k in range(4):
        out[ok & (v <= EDGES[k]) & (v > EDGES[k + 1])] = k + 1
    out[ok & (v <= EDGES[4])] = 5
    return out


def build_weights(cells: pd.DataFrame) -> pd.DataFrame:
    g = gpd.GeoDataFrame({"cell": cells.index},
                         geometry=[shapely.box(x - HALF, y - HALF, x + HALF, y + HALF) for y, x in zip(cells.lat, cells.lon)],
                         crs=4326)
    d = gpd.read_parquet(REF / "districts.parquet")[["dist_lgd", "geometry"]]
    ov = gpd.overlay(g, d, how="intersection", keep_geom_type=True)
    ov["w_km2"] = (ov.to_crs(EQUAL_AREA).area / 1e6).round(3)
    w = ov[ov.w_km2 > 0.01][["cell", "dist_lgd", "w_km2"]].sort_values(["dist_lgd", "cell"])
    missing = sorted(set(d.dist_lgd) - set(w.dist_lgd))
    if missing:
        log.warning("districts with no IDM cell: %s", missing)
    return w


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    paths = idm.fetch_all()
    grid = idm.read(paths[-1])[["lat", "lon"]]
    grid.index.name = "cell"
    wp = REF / "idm_district_weights.csv"
    w = build_weights(grid)
    w.to_csv(wp, index=False)
    codes = np.sort(w.dist_lgd.unique())
    W = sparse.csr_matrix((w.w_km2, (w.cell, np.searchsorted(codes, w.dist_lgd))), shape=(len(grid), len(codes)))
    key = grid.lat.round(3).astype(str) + "," + grid.lon.round(3).astype(str)

    rows = []
    for p in paths:
        f = idm.read(p)
        f.index = f.lat.round(3).astype(str) + "," + f.lon.round(3).astype(str)
        v = f.cdi.reindex(key).to_numpy(float)  # align to the reference grid order
        cls = classify(v)
        valid = (cls >= 0).astype(float)
        den = valid @ W
        tot = np.ones(len(v)) @ W
        rec = {"week": pd.Timestamp(idm.week_of(p)), "dist_lgd": codes,
               "coverage": np.where(tot > 0, den / tot, 0)}
        with np.errstate(invalid="ignore", divide="ignore"):
            rec["cdi_mean"] = np.where(den > 0, (np.nan_to_num(v) * valid) @ W / den, np.nan)
            for k, c in enumerate(CLASSES):
                rec[f"pct_{c}"] = np.where(den > 0, 100 * ((cls == k).astype(float) @ W) / den, np.nan)
        rows.append(pd.DataFrame(rec))
    df = pd.concat(rows, ignore_index=True)
    num = [c for c in df.columns if c.startswith(("pct_", "cdi", "coverage"))]
    df[num] = df[num].astype("float32").round(2)
    PROC.mkdir(parents=True, exist_ok=True)
    df.to_parquet(PROC / "idm_weekly.parquet", index=False)

    weeks = sorted(df.week.unique())
    last, prev4 = weeks[-1], weeks[-5]
    L = df[df.week == last].set_index("dist_lgd")
    P = df[df.week == prev4].set_index("dist_lgd")
    recent = df[df.week.isin(weeks[-26:])]
    d1p = recent.assign(v=recent.pct_d1 + recent.pct_d2 + recent.pct_d3 + recent.pct_d4)
    out = {}
    for code, r in L.iterrows():
        if np.isnan(r.cdi_mean):
            continue
        drought = r[[f"pct_{c}" for c in CLASSES[1:]]].sum()
        out[int(code)] = {
            "cdi_mean": round(float(r.cdi_mean), 2),
            "class_of_mean": CLASSES[int(classify(np.array([r.cdi_mean]))[0])],
            "pct": {c: round(float(r[f"pct_{c}"]), 1) for c in CLASSES},
            "pct_in_drought_d0plus": round(float(drought), 1),
            "pct_d1plus_4wk_ago": round(float(P.loc[code, ["pct_d1", "pct_d2", "pct_d3", "pct_d4"]].sum()), 1) if code in P.index else None,
            "d1plus_last26": [round(float(x), 1) for x in d1p[d1p.dist_lgd == code].sort_values("week").v],
        }
    doc = {"week": str(pd.Timestamp(last).date()), "weeks_in_series": [str(pd.Timestamp(x).date()) for x in weeks[-26:]],
           "first_week_available": str(pd.Timestamp(weeks[0]).date()),
           "classes": {"none": "> -0.5", "d0": "-0.8 to -0.5 (abnormally dry)", "d1": "-1.3 to -0.8 (moderate)",
                       "d2": "-1.6 to -1.3 (severe)", "d3": "-2.0 to -1.6 (extreme)", "d4": "<= -2.0 (exceptional)"},
           "source": "India Drought Monitor, Water and Climate Lab, IIT Gandhinagar (indiadroughtmonitor.in). "
                     "Combined Drought Index; district values = area-weighted over LGD boundaries. Detected drought, not an official declaration.",
           "districts": out}
    WEB.mkdir(parents=True, exist_ok=True)
    (WEB / "idm.json").write_text(webjson.dumps(doc, separators=(",", ":")))
    cls = pd.Series([v["class_of_mean"] for v in out.values()]).value_counts().to_dict()
    log.info("week %s: %d districts; class of district mean: %s", doc["week"], len(out), cls)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
