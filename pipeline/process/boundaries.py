"""Phase 1: district boundaries and the district master table.

Source: india-geodata release `admin/districts`, file LGD_Districts (CC0;
785 polygons, vintage Dec 2023, keyed on LGD district code `dist_lgd`).

Outputs
  data/reference/district_master.csv   one row per real district (committed)
  data/reference/districts.parquet     full-resolution polygons for spatial joins (local)
  web/data/districts.geojson           simplified polygons for the map (committed, < 2 MB)
  web/data/india_outline.geojson       national outline incl. PoK, from the same polygons

Known issues, recorded in district_master.notes:
  - Mirpur and Muzaffarabad (PoK) carry dist_lgd 0. They are kept in the outline
    and map (official map of India) but are not districts in the master table.
  - Rajasthan abolished 9 of these districts in Dec 2024. They stay on the map,
    flagged, until we have an authoritative merged boundary.

Usage: python -m pipeline.process.boundaries
"""

from __future__ import annotations

import json

from pipeline import webjson
import shutil
import subprocess
import urllib.request
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw" / "boundaries"
REF = REPO / "data" / "reference"
WEB = REPO / "web" / "data"
SRC_URL = "https://github.com/yashveeeeeeer/india-geodata/releases/download/admin/districts/LGD_Districts.geojsonl.7z"
SRC = RAW / "LGD_Districts.geojsonl"

# India-centred Albers equal-area, for areas in km2.
EQUAL_AREA = "+proj=aea +lat_1=12 +lat_2=28 +lat_0=20 +lon_0=78 +datum=WGS84 +units=m"
MAX_WEB_BYTES = 2_000_000

# Abolished by the Government of Rajasthan, 28 Dec 2024. LGD codes from this file.
RAJASTHAN_ABOLISHED_2024 = {
    769: "Dudu", 771: "Gangapurcity", 773: "Neem Ka Thana", 776: "Anoopgarh",
    778: "Jodhpur Gramin", 779: "Sanchor", 780: "Shahpura", 781: "Kekri", 783: "Jaipur Gramin",
}


def fetch() -> None:
    if SRC.exists():
        return
    RAW.mkdir(parents=True, exist_ok=True)
    arc = RAW / "LGD_Districts.geojsonl.7z"
    urllib.request.urlretrieve(SRC_URL, arc)
    tar = shutil.which("bsdtar") or "tar"  # bsdtar reads 7z (macOS tar is bsdtar; on Linux install libarchive-tools)
    subprocess.run([tar, "-xf", arc.name], cwd=RAW, check=True)
    if not SRC.exists():
        raise FileNotFoundError(f"{SRC} not found after extracting {arc}")


def polygonal(geom):
    """make_valid can return GeometryCollections; keep only the polygon parts."""
    g = shapely.make_valid(geom)
    if g.geom_type in ("Polygon", "MultiPolygon"):
        return g
    parts = [p for p in getattr(g, "geoms", []) if p.geom_type in ("Polygon", "MultiPolygon")]
    return shapely.union_all(parts)


def load() -> gpd.GeoDataFrame:
    g = gpd.read_file(SRC)
    g = g[["dist_lgd", "dtname", "stname", "state_lgd", "year_stat", "geometry"]].copy()
    g["was_invalid"] = ~g.is_valid
    g["geometry"] = g.geometry.apply(polygonal)
    g["dist_lgd"] = g["dist_lgd"].astype(int)
    g["is_pok"] = g["dist_lgd"].eq(0)
    return g


def master(g: gpd.GeoDataFrame) -> pd.DataFrame:
    d = g[~g.is_pok].copy()
    if d["dist_lgd"].duplicated().any():
        raise ValueError(f"duplicate LGD codes: {d[d.dist_lgd.duplicated()].dist_lgd.tolist()}")
    rp = d.geometry.representative_point()
    m = pd.DataFrame({
        "dist_lgd": d["dist_lgd"],
        "district": d["dtname"].str.strip(),
        "state": d["stname"].str.strip().str.title().str.replace(" And ", " and ").str.replace("&", "and"),
        "state_lgd": d["state_lgd"].astype(int),
        "area_km2": (d.to_crs(EQUAL_AREA).area / 1e6).round(1),
        "lat": rp.y.round(4),
        "lon": rp.x.round(4),
        "boundary_vintage": d["year_stat"].replace("", "unknown"),
        "notes": d["dist_lgd"].map(lambda c: "abolished Dec 2024 (Rajasthan); boundary kept until merged map available"
                                   if c in RAJASTHAN_ABOLISHED_2024 else ""),
    })
    return m.sort_values(["state", "district"]).reset_index(drop=True)


def simplify_for_web(g: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, float]:
    """Topology-preserving simplification of the whole coverage (shared borders
    stay shared), increasing tolerance until the GeoJSON fits MAX_WEB_BYTES."""
    for tol in (0.005, 0.01, 0.015, 0.02, 0.03, 0.04):
        s = g[["dist_lgd", "dtname", "stname", "is_pok", "geometry"]].copy()
        s["geometry"] = shapely.coverage_simplify(s.geometry.values, tolerance=tol)
        s["geometry"] = shapely.set_precision(s.geometry.values, 0.001)  # ~100 m grid
        s = s[~s.is_empty]
        if len(to_geojson(s)) <= MAX_WEB_BYTES:
            return s, tol
    raise ValueError("could not get web boundaries under the size limit")


def to_geojson(s: gpd.GeoDataFrame) -> bytes:
    feats = []
    for r in s.itertuples():
        props = {"lgd": None if r.is_pok else int(r.dist_lgd), "n": r.dtname.strip(), "s": r.stname.strip().title()}
        if r.is_pok:
            props["pok"] = True
        feats.append({"type": "Feature", "properties": props,
                      "geometry": json.loads(shapely.to_geojson(r.geometry))})
    return json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":")).encode()


def ensure_parquet() -> Path:
    """Full-resolution district polygons (data/reference/districts.parquet is not in git).
    Built from the source release when missing; the daily run needs it only to place new wells."""
    p = REF / "districts.parquet"
    if not p.exists():
        fetch()
        g = load()
        REF.mkdir(parents=True, exist_ok=True)
        g[~g.is_pok].drop(columns=["is_pok", "was_invalid"]).to_parquet(p)
    return p


def main() -> int:
    fetch()
    g = load()
    m = master(g)
    REF.mkdir(parents=True, exist_ok=True)
    m.to_csv(REF / "district_master.csv", index=False)
    full = g[~g.is_pok].drop(columns=["is_pok", "was_invalid"])
    full.to_parquet(REF / "districts.parquet")

    s, tol = simplify_for_web(g)
    WEB.mkdir(parents=True, exist_ok=True)
    (WEB / "districts.geojson").write_bytes(to_geojson(s))
    outline = shapely.set_precision(shapely.union_all(s.geometry.values), 0.001)
    (WEB / "india_outline.geojson").write_text(webjson.dumps(
        {"type": "Feature", "properties": {}, "geometry": json.loads(shapely.to_geojson(outline))}, separators=(",", ":")))

    report = {
        "polygons_in_source": len(g),
        "districts_in_master": len(m),
        "pok_polygons_outline_only": int(g.is_pok.sum()),
        "invalid_geometries_fixed": int(g.was_invalid.sum()),
        "rajasthan_abolished_flagged": len(RAJASTHAN_ABOLISHED_2024),
        "states": int(m.state.nunique()),
        "web_tolerance_deg": tol,
        "web_geojson_bytes": (WEB / "districts.geojson").stat().st_size,
        "outline_bytes": (WEB / "india_outline.geojson").stat().st_size,
    }
    (REF / "boundaries_report.json").write_text(webjson.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
