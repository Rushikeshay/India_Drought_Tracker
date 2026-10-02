"""Phase 2: IMD gridded rainfall -> district values.

Grid -> district: area-weighted mean of the 0.25 deg cells overlapping each
district (weights = overlap area in km2), using only cells with data that day.

Stored (small; daily grids are deleted after reduction):
  data/reference/imd_district_weights.csv       cell -> district overlap weights
  data/processed/rain_monthly.parquet           dist_lgd, year, month, mm   (1951 - last full year)
  data/processed/rain_daily_normal.parquet      dist_lgd, month, day, mm    (NORMAL_PERIOD mean)
  data/raw/imd/reduced/<year>.parquet           per-year daily district series (local checkpoint)

Usage:
  python -m pipeline.process.rain weights
  python -m pipeline.process.rain history [--start 1951] [--end 2025] [--keep-grids]
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from scipy import sparse

from pipeline.sources import imd

REPO = Path(__file__).resolve().parents[2]
REF = REPO / "data" / "reference"
PROC = REPO / "data" / "processed"
REDUCED = REPO / "data" / "raw" / "imd" / "reduced"
EQUAL_AREA = "+proj=aea +lat_1=12 +lat_2=28 +lat_0=20 +lon_0=78 +datum=WGS84 +units=m"
NORMAL_PERIOD = (1971, 2020)  # IMD's current LPA period; verified against IMD pages in validation
START_YEAR = 1951

log = logging.getLogger("rain")


# ---------- weights ----------

def build_weights(mask_year: int = 2025) -> pd.DataFrame:
    """Overlap (km2) of every IMD land cell with every district."""
    land = ~np.isnan(imd.read(imd.year_file(mask_year))).all(axis=0)  # cells with data on any day
    h = 0.125
    rows = []
    for i, la in enumerate(imd.LATS):
        for j, lo in enumerate(imd.LONS):
            if land[i, j]:
                rows.append((i * imd.NLON + j, shapely.box(lo - h, la - h, lo + h, la + h)))
    cells = gpd.GeoDataFrame({"cell": [r[0] for r in rows]}, geometry=[r[1] for r in rows], crs=4326)
    d = gpd.read_parquet(REF / "districts.parquet")[["dist_lgd", "geometry"]]
    ov = gpd.overlay(cells, d, how="intersection", keep_geom_type=True)
    ov["w_km2"] = ov.to_crs(EQUAL_AREA).area / 1e6
    w = ov[ov.w_km2 > 0.01][["cell", "dist_lgd", "w_km2"]]

    # Island districts outside the IMD land grid get no rainfall value: borrowing a
    # distant mainland cell would be invented data.
    missing = sorted(set(d.dist_lgd) - set(w.dist_lgd))
    if missing:
        log.warning("districts with no IMD land cell (no rainfall data): %s", missing)
        (REF / "imd_no_coverage.csv").write_text("dist_lgd\n" + "\n".join(map(str, missing)) + "\n")
    w["w_km2"] = w.w_km2.round(3)
    return w.sort_values(["dist_lgd", "cell"]).reset_index(drop=True)


def load_weights() -> tuple[sparse.csr_matrix, np.ndarray]:
    w = pd.read_csv(REF / "imd_district_weights.csv")
    codes = np.sort(w.dist_lgd.unique())
    col = np.searchsorted(codes, w.dist_lgd.to_numpy())
    W = sparse.csr_matrix((w.w_km2.to_numpy(), (w.cell.to_numpy(), col)), shape=(imd.NLAT * imd.NLON, len(codes)))
    return W, codes


def to_districts(grid: np.ndarray, W: sparse.csr_matrix) -> np.ndarray:
    """(days, lat, lon) -> (days, districts) area-weighted mean over cells with data."""
    flat = grid.reshape(grid.shape[0], -1)
    valid = ~np.isnan(flat)
    num = sparse.csr_matrix(np.where(valid, flat, 0.0)) @ W
    den = sparse.csr_matrix(valid.astype(np.float64)) @ W
    num, den = num.toarray(), den.toarray()
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)


# ---------- history ----------

def reduce_year(year: int, W, codes, keep_grid: bool) -> pd.DataFrame:
    out = REDUCED / f"{year}.parquet"
    if out.exists():
        return pd.read_parquet(out)
    path = imd.year_file(year)
    vals = to_districts(imd.read(path), W).astype(np.float32)
    days = pd.date_range(f"{year}-01-01", periods=vals.shape[0], freq="D")
    df = pd.DataFrame(vals, index=days, columns=codes)
    REDUCED.mkdir(parents=True, exist_ok=True)
    df.columns = df.columns.astype(str)
    df.to_parquet(out)
    if not keep_grid:
        path.unlink()
    return df


def history(start: int, end: int, keep_grids: bool) -> None:
    W, codes = load_weights()
    monthly, nsum, ncount = [], None, 0
    for y in range(start, end + 1):
        df = reduce_year(y, W, codes, keep_grids)
        m = df.resample("MS").sum(min_count=1)
        m = m.stack().rename("mm").reset_index()
        m.columns = ["date", "dist_lgd", "mm"]
        monthly.append(m)
        if NORMAL_PERIOD[0] <= y <= NORMAL_PERIOD[1]:
            md = df.groupby([df.index.month, df.index.day]).sum(min_count=1)
            nsum = md if nsum is None else nsum.add(md, fill_value=0)
            ncount += 1
        log.info("%d done", y)

    mon = pd.concat(monthly, ignore_index=True)
    mon["year"] = mon.date.dt.year.astype("int16")
    mon["month"] = mon.date.dt.month.astype("int8")
    mon["dist_lgd"] = mon.dist_lgd.astype("int32")
    mon["mm"] = mon.mm.astype("float32").round(2)
    PROC.mkdir(parents=True, exist_ok=True)
    mon[["dist_lgd", "year", "month", "mm"]].to_parquet(PROC / "rain_monthly.parquet", index=False)

    if nsum is not None and ncount == NORMAL_PERIOD[1] - NORMAL_PERIOD[0] + 1:
        # Feb 29 occurs in 12 or 13 of 50 years: scale it by its own count.
        leap = sum(1 for y in range(NORMAL_PERIOD[0], NORMAL_PERIOD[1] + 1) if imd.days_in_year(y) == 366)
        norm = nsum / ncount
        norm.loc[(2, 29)] = nsum.loc[(2, 29)] / leap
        n = norm.stack().rename("mm").reset_index()
        n.columns = ["month", "day", "dist_lgd", "mm"]
        n["dist_lgd"] = n.dist_lgd.astype("int32")
        n["mm"] = n.mm.astype("float32")
        n.to_parquet(PROC / "rain_daily_normal.parquet", index=False)
    else:
        log.warning("normal period %s not fully covered (%d years); daily normals not written", NORMAL_PERIOD, ncount)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("weights")
    h = sub.add_parser("history")
    h.add_argument("--start", type=int, default=START_YEAR)
    h.add_argument("--end", type=int, default=pd.Timestamp.today().year - 1)
    h.add_argument("--keep-grids", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if a.cmd == "weights":
        w = build_weights()
        w.to_csv(REF / "imd_district_weights.csv", index=False)
        log.info("weights: %d rows, %d districts", len(w), w.dist_lgd.nunique())
    else:
        history(a.start, a.end, a.keep_grids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
