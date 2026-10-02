"""Phase 0: how many of India's districts can we cover without an India IP?

Denominator: 785 districts in LGD_Districts (india-geodata release admin/districts,
CC0; vintage Dec 2023). Wells are assigned to districts by lat/lon (spatial join),
not by the district name in the source file.

Groundwater sources (NWDP, reachable from anywhere):
  manual quarterly CSVs (1991-2025)         data/raw/nwdp/*manual*.csv
  telemetry six-hourly 2021-2025 / 2026-     data/raw/nwdp/tele2021/, tele2026/

"Season-years" for a well = the number of distinct years with a reading in the
post-monsoon window (Aug-Nov), the window that matters for the classification at
this time of year. Pre-monsoon (Mar-May) is reported too.

Writes notebooks/phase0/results/coverage.json and data/raw/coverage_by_district.csv.
"""

import glob
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
NOW = pd.Timestamp("2026-10-01")
LIVE_SINCE = NOW - pd.Timedelta(days=60)
TIME_FMT = "%d-%m-%Y %H:%M"


def districts() -> gpd.GeoDataFrame:
    g = gpd.read_file(next((RAW / "boundaries").glob("LGD_Districts.geojsonl")))
    return g[["dist_lgd", "dtname", "stname", "geometry"]]


def season_years(t: pd.Series, months) -> int:
    return t[t.dt.month.isin(months)].dt.year.nunique()


def manual_wells() -> pd.DataFrame:
    frames = []
    for f in glob.glob(str(RAW / "nwdp" / "*manual*quarterly*.csv")):
        d = pd.read_csv(f, usecols=["Station", "Latitude", "Longitude", "Data Acquisition Time"], low_memory=False)
        frames.append(d)
    m = pd.concat(frames, ignore_index=True)
    m["t"] = pd.to_datetime(m["Data Acquisition Time"], format=TIME_FMT, errors="coerce")
    for c in ("Latitude", "Longitude"):
        m[c] = pd.to_numeric(m[c], errors="coerce")
    m = m.dropna(subset=["t", "Latitude", "Longitude"])
    m["loc"] = m.Latitude.round(4).astype(str) + "," + m.Longitude.round(4).astype(str)
    a = m[(m.t >= "2000-01-01") & (m.t < "2024-01-01")]
    b = m[m.t >= "2024-01-01"]
    w = m.groupby("loc").agg(lat=("Latitude", "first"), lon=("Longitude", "first"), last=("t", "max")).reset_index()
    w["post_00_23"] = a.groupby("loc").t.apply(lambda s: season_years(s, (8, 9, 10, 11))).reindex(w["loc"]).fillna(0).values
    w["pre_00_23"] = a.groupby("loc").t.apply(lambda s: season_years(s, (3, 4, 5))).reindex(w["loc"]).fillna(0).values
    w["post_all"] = m.groupby("loc").t.apply(lambda s: season_years(s, (8, 9, 10, 11))).reindex(w["loc"]).values
    w["any_00_23"] = w["loc"].isin(a["loc"])
    w["any_24"] = w["loc"].isin(b["loc"])
    return w


def telemetry_wells() -> pd.DataFrame:
    parts = []
    for f in glob.glob(str(RAW / "nwdp" / "tele20*" / "*.csv")):
        for d in pd.read_csv(f, usecols=["Station", "Latitude", "Longitude", "Data Acquisition Time"],
                             chunksize=2_000_000, low_memory=False):
            d["t"] = pd.to_datetime(d["Data Acquisition Time"], format=TIME_FMT, errors="coerce")
            d = d.dropna(subset=["t"])
            d["y"] = d.t.dt.year
            d["post"] = d.t.dt.month.isin((8, 9, 10, 11))
            parts.append(d.groupby(["Station", "y"]).agg(lat=("Latitude", "first"), lon=("Longitude", "first"),
                                                        last=("t", "max"), post=("post", "any")).reset_index())
    t = pd.concat(parts)
    for c in ("lat", "lon"):
        t[c] = pd.to_numeric(t[c], errors="coerce")
    w = t.groupby("Station").agg(lat=("lat", "first"), lon=("lon", "first"), last=("last", "max"),
                                 first_year=("y", "min")).reset_index()
    w["post_years"] = t[t.post].groupby("Station").y.nunique().reindex(w.Station).fillna(0).values
    w["any_24"] = w["last"] >= "2024-01-01"
    w["live"] = w["last"] >= LIVE_SINCE
    return w.dropna(subset=["lat", "lon"])


def attach_manual_history(tel: pd.DataFrame, man: pd.DataFrame, max_m: float = 50) -> pd.DataFrame:
    """Nearest manual well within max_m metres; its post-monsoon years count as history.
    Co-location is NOT proof of the same well (see docs/sources.md); this is an upper bound."""
    ml = np.radians(man[["lat", "lon"]].to_numpy(float))
    best, dist = [], []
    for la, lo in np.radians(tel[["lat", "lon"]].to_numpy(float)):
        dd = np.hypot((ml[:, 1] - lo) * np.cos(la), ml[:, 0] - la) * 6_371_000
        i = int(dd.argmin())
        best.append(i)
        dist.append(dd[i])
    tel = tel.copy()
    tel["man_dist_m"] = dist
    tel["man_post_years"] = np.where(np.array(dist) <= max_m, man["post_all"].to_numpy()[best], 0)
    tel["hist_years"] = tel["post_years"] + tel["man_post_years"]  # upper bound: years can overlap
    return tel


def join(points: pd.DataFrame, dist: gpd.GeoDataFrame) -> pd.DataFrame:
    g = gpd.GeoDataFrame(points, geometry=gpd.points_from_xy(points.lon, points.lat), crs=4326)
    j = gpd.sjoin(g, dist[["dist_lgd", "geometry"]], how="left", predicate="within")
    return pd.DataFrame(j.drop(columns=["geometry", "index_right"]))


def count(df: pd.DataFrame, mask, n: int, total: int) -> dict:
    c = df[mask].groupby("dist_lgd").size()
    k = int((c >= n).sum())
    return {"districts": k, "pct": round(100 * k / total, 1)}


def main():
    D = districts()
    N = len(D)
    out = {"denominator_districts": N, "as_of": str(NOW.date())}

    # Rain: IMD 0.25 deg grid centres inside each district
    lat = np.linspace(6.5, 38.5, 129)
    lon = np.linspace(66.5, 100.0, 135)
    LA, LO = np.meshgrid(lat, lon)
    cells = pd.DataFrame({"lat": LA.ravel(), "lon": LO.ravel()})
    cj = join(cells, D).dropna(subset=["dist_lgd"])
    per = cj.groupby("dist_lgd").size()
    out["rain"] = {
        "districts_with_>=1_grid_centre": int(len(per)),
        "districts_with_0_grid_centres_(use_area_weighting)": int(N - len(per)),
        "note": "IMD 1901-present and real-time cover all of India; small districts need area-weighted overlay",
    }

    mw = manual_wells()
    man = join(mw, D)
    tel = join(attach_manual_history(telemetry_wells(), mw), D)
    out["wells"] = {"manual": len(man), "telemetry": len(tel),
                    "manual_outside_polygons": int(man.dist_lgd.isna().sum()),
                    "telemetry_outside_polygons": int(tel.dist_lgd.isna().sum())}

    out["gw_2000_2023"] = {
        ">=1 well with any reading": count(man, man.any_00_23, 1, N),
        ">=3 wells with >=5 post-monsoon years": count(man, man.post_00_23 >= 5, 3, N),
        ">=5 wells with >=10 post-monsoon years (plan rule)": count(man, man.post_00_23 >= 10, 5, N),
        ">=5 wells with >=10 pre-monsoon years": count(man, man.pre_00_23 >= 10, 5, N),
    }
    recent = pd.concat([man.loc[man.any_24, ["dist_lgd"]], tel.loc[tel.any_24, ["dist_lgd"]]])
    out["gw_2024_now"] = {
        ">=1 well with a 2024+ reading (manual or telemetry)": count(recent, pd.Series(True, index=recent.index), 1, N),
        ">=1 live telemetry well (last 60 days)": count(tel, tel.live, 1, N),
        ">=3 live wells": count(tel, tel.live, 3, N),
        ">=3 live wells with >=5 post-monsoon years (telemetry + co-located manual, upper bound)": count(tel, tel.live & (tel.hist_years >= 5), 3, N),
        ">=3 live wells with >=5 post-monsoon years (telemetry only)": count(tel, tel.live & (tel.post_years >= 5), 3, N),
        ">=5 live wells with >=10 post-monsoon years (plan rule, upper bound)": count(tel, tel.live & (tel.hist_years >= 10), 5, N),
    }
    tel_first = tel.groupby("first_year").size().to_dict()
    out["telemetry_first_year_counts"] = {str(k): int(v) for k, v in tel_first.items()}

    res = REPO / "notebooks" / "phase0" / "results"
    (res / "coverage.json").write_text(json.dumps(out, indent=2))
    by = D.drop(columns="geometry").copy()
    by["gw_wells_00_23_10y"] = by.dist_lgd.map(man[man.post_00_23 >= 10].groupby("dist_lgd").size()).fillna(0).astype(int)
    by["gw_live_wells"] = by.dist_lgd.map(tel[tel.live].groupby("dist_lgd").size()).fillna(0).astype(int)
    by["imd_cells"] = by.dist_lgd.map(per).fillna(0).astype(int)
    by.to_csv(RAW / "coverage_by_district.csv", index=False)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
