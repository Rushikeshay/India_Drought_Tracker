"""IIT Gandhinagar India Drought Monitor (github.com/wcl-iitgn/IndianDroughtMonitor).

Weekly Combined Drought Index (CDI) grids: data/Drough_TS/CDI_YYYYMMDD.txt
("lat lon value", 0.25 deg, cell centres at .125/.375/...), since 2021-07-14.
Credit: Water and Climate Lab, IIT Gandhinagar. Used as a "detected drought" layer
(owner's decision 2026-10-01); never labelled as an official declaration.

Usage: python -m pipeline.sources.idm
"""

from __future__ import annotations

import logging
import os
import re
from datetime import date
from pathlib import Path

import pandas as pd
import requests

REPO_API = "https://api.github.com/repos/wcl-iitgn/IndianDroughtMonitor/contents/data/Drough_TS"
RAW_URL = "https://raw.githubusercontent.com/wcl-iitgn/IndianDroughtMonitor/main/data/Drough_TS/{}"
RAW = Path(__file__).resolve().parents[2] / "data" / "raw" / "idm"
NAME = re.compile(r"^CDI_(\d{8})\.txt$")

log = logging.getLogger("idm")


def _session() -> requests.Session:
    s = requests.Session()
    if os.environ.get("GITHUB_TOKEN"):
        s.headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    return s


def listing() -> dict[date, str]:
    r = _session().get(REPO_API, timeout=60)
    r.raise_for_status()
    out = {}
    for x in r.json():
        m = NAME.match(x["name"])
        if m:
            out[pd.Timestamp(m[1]).date()] = x["name"]
    if not out:
        raise RuntimeError("no CDI files listed")
    return out


def fetch_all() -> list[Path]:
    RAW.mkdir(parents=True, exist_ok=True)
    s = _session()
    paths = []
    for d, name in sorted(listing().items()):
        p = RAW / name
        if not p.exists() or p.stat().st_size < 1000:
            r = s.get(RAW_URL.format(name), timeout=60)
            r.raise_for_status()
            p.write_bytes(r.content)
            log.info("downloaded %s", name)
        paths.append(p)
    return paths


def read(p: Path) -> pd.DataFrame:
    return pd.read_csv(p, sep=r"\s+", header=None, names=["lat", "lon", "cdi"])


def week_of(p: Path) -> date:
    return pd.Timestamp(NAME.match(p.name)[1]).date()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(len(fetch_all()), "weekly CDI files")
