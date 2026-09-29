"""India-WRIS CGWB groundwater levels -> data/wris/.

indiawris.gov.in is on NICNET and refuses non-India IPs, so this runs on the
Oracle Cloud VM in India (deploy/oracle/). See docs/sources.md §3.

Recipe from neer-vazhvu's pan-India playbook (MIT):
  POST /Dataset/Ground%20Water%20Level with ALL params in the query string.
  A blank districtName returns zero rows, so iterate every district. Paginate
  until a short page.

Per run, for every district: fetch from (watermark - OVERLAP_DAYS) to today,
so late-entered manual readings are picked up. Outputs (committed):
  data/wris/manual/<STATE>.csv              every manual reading, deduplicated
  data/wris/telemetric_monthly/<STATE>.csv  telemetric readings reduced to
                                            per-station monthly median/min/max/n
  data/wris/manifest.json                   per-district watermark + counts
  data/reference/wris_districts.csv         WRIS state/district master list
Full raw responses are cached (not committed) in data/raw/wris/<run date>/.

Values are stored exactly as served: sign conventions differ by station family
and are resolved in processing, never here.

Usage: python -m pipeline.sources.wris [--states "Maharashtra" ...] [--since YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

BASE = "https://indiawris.gov.in"
GWL = f"{BASE}/Dataset/Ground%20Water%20Level"
PAGE = 9000
FIRST_START = "2023-01-01"  # NWDP bulk history ends 2023-2025 by state; overlap with it
OVERLAP_DAYS = 180
DELAY = 1.0  # seconds between requests, to be polite to a government server

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "wris"
RAW = REPO / "data" / "raw" / "wris"
MASTER = REPO / "data" / "reference" / "wris_districts.csv"
MANIFEST = OUT / "manifest.json"

KEEP = ["stationCode", "stationName", "latitude", "longitude", "district", "tehsil",
        "agencyName", "dataAcquisitionMode", "stationStatus", "dataTime", "dataValue", "unit"]

log = logging.getLogger("wris")


class WrisError(RuntimeError):
    pass


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": BASE,
        "Referer": f"{BASE}/dataSet/",
        "User-Agent": "Mozilla/5.0 (India Drought Tracker; github.com/Rushikeshay/India_Drought_Tracker)",
    })
    return s


def post(s: requests.Session, url: str, *, tries: int = 4, **kw):
    kw.setdefault("timeout", 180)
    for i in range(tries):
        try:
            r = s.post(url, **kw)
            if r.status_code < 500:
                r.raise_for_status()
                time.sleep(DELAY)
                return r.json()
            log.warning("%s -> HTTP %s", url, r.status_code)
        except (requests.ConnectionError, requests.Timeout) as exc:
            log.warning("%s -> %r", url, exc)
        time.sleep(10 * (i + 1))
    raise WrisError(f"{url} failed after {tries} tries")


def as_list(j) -> list:
    if isinstance(j, list):
        return j
    if isinstance(j, dict):
        for k in ("data", "content", "result"):
            if isinstance(j.get(k), list):
                return j[k]
    raise WrisError(f"unexpected response shape: {str(j)[:300]}")


def first(d: dict, *keys):
    for k in keys:
        if d.get(k) not in (None, ""):
            return d[k]
    return None


def master_list(s: requests.Session) -> pd.DataFrame:
    """All (state, district) pairs WRIS knows for the Ground Water Level dataset."""
    ds = as_list(post(s, f"{BASE}/DataSet/DataSetList", json={"headers": {"normalizedNames": {}, "lazyUpdate": None}}))
    gwl = [d for d in ds if str(first(d, "datasetname", "dataSetName", "dname", "name") or "").strip().lower() == "ground water level"]
    if not gwl:
        raise WrisError(f"'Ground Water Level' not in dataset list: {[first(d, 'datasetname', 'dataSetName', 'dname', 'name') for d in ds]}")
    dcode = first(gwl[0], "datasetcode", "dcode", "dataSetCode")
    rows = []
    for st in as_list(post(s, f"{BASE}/masterState/StateList", json={"datasetcode": dcode})):
        scode, sname = first(st, "statecode", "stateCode"), first(st, "statename", "stateName", "name")
        for d in as_list(post(s, f"{BASE}/masterDistrict/getDistrictbyState", json={"statecode": scode, "datasetcode": dcode})):
            rows.append({"state": sname, "state_code": scode,
                         "district": first(d, "districtname", "districtName", "name"),
                         "district_code": first(d, "districtcode", "districtCode")})
    df = pd.DataFrame(rows).sort_values(["state", "district"])
    if df.empty or df["district"].isna().any():
        raise WrisError("empty or malformed district master list")
    return df


def fetch_district(s, state: str, district: str, start: str, end: str) -> list[dict]:
    rows, page = [], 0
    while True:
        params = {"stateName": state, "districtName": district, "agencyName": "CGWB",
                  "startdate": start, "enddate": end, "download": "false", "page": page, "size": PAGE}
        batch = as_list(post(s, GWL, params=params))
        rows.extend(batch)
        if len(batch) < PAGE:
            return rows
        page += 1


def slug(x: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", x).strip("_")


def merge_state(state: str, new: pd.DataFrame) -> dict:
    """Merge new rows into the committed per-state files. Returns counts."""
    new = new.reindex(columns=KEEP)
    new["dataTime"] = pd.to_datetime(new["dataTime"], errors="coerce")
    bad = new["dataTime"].isna().sum()
    if bad:
        log.warning("%s: %d rows with unparseable dataTime dropped", state, bad)
    new = new.dropna(subset=["dataTime"])
    tele = new["dataAcquisitionMode"].fillna("").str.lower().str.startswith("telemetr")

    # Manual readings: keep all, dedupe on station + time.
    mpath = OUT / "manual" / f"{slug(state)}.csv"
    man = new[~tele]
    if mpath.exists():
        man = pd.concat([pd.read_csv(mpath, parse_dates=["dataTime"]), man])
    man = man.drop_duplicates(["stationCode", "dataTime"], keep="last").sort_values(["stationCode", "dataTime"])
    mpath.parent.mkdir(parents=True, exist_ok=True)
    man.to_csv(mpath, index=False, date_format="%Y-%m-%dT%H:%M:%S")

    # Telemetric: monthly stats per station. Recompute months touched by this pull
    # from the raw rows fetched now (they cover whole months after the overlap start).
    tpath = OUT / "telemetric_monthly" / f"{slug(state)}.csv"
    t = new[tele].copy()
    t["month"] = t["dataTime"].dt.strftime("%Y-%m")
    t["v"] = pd.to_numeric(t["dataValue"], errors="coerce")
    agg = (t.groupby(["stationCode", "month"])
             .agg(stationName=("stationName", "last"), latitude=("latitude", "last"), longitude=("longitude", "last"),
                  district=("district", "last"), median=("v", "median"), min=("v", "min"), max=("v", "max"),
                  n=("v", "count"), unit=("unit", "last"))
             .reset_index())
    if tpath.exists():
        old = pd.read_csv(tpath, dtype={"month": str})
        # the first month of this pull may be partial; keep the old value for it
        if not agg.empty:
            first_month = t["month"].min()
            agg = agg[agg["month"] > first_month]
        agg = pd.concat([old, agg]).drop_duplicates(["stationCode", "month"], keep="last")
    agg = agg.sort_values(["stationCode", "month"])
    tpath.parent.mkdir(parents=True, exist_ok=True)
    agg.to_csv(tpath, index=False)
    return {"manual_rows": len(man), "telemetric_station_months": len(agg)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--states", nargs="*", help="limit to these WRIS state names")
    ap.add_argument("--since", help="override start date for every district (YYYY-MM-DD)")
    ap.add_argument("--max-districts", type=int, help="stop after N districts (testing)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    s = session()
    master = master_list(s)
    MASTER.parent.mkdir(parents=True, exist_ok=True)
    master.to_csv(MASTER, index=False)
    log.info("master list: %d states, %d districts", master["state"].nunique(), len(master))

    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    today = date.today().isoformat()
    run_dir = RAW / today
    failures, done = [], 0
    todo = master if not a.states else master[master["state"].isin(a.states)]
    if todo.empty:
        raise WrisError(f"no districts match {a.states}")

    for state, grp in todo.groupby("state"):
        frames = []
        for district in grp["district"]:
            key = f"{state}|{district}"
            wm = manifest.get(key, {}).get("last_data_time")
            start = a.since or (max(FIRST_START, (date.fromisoformat(wm[:10]) - timedelta(days=OVERLAP_DAYS)).isoformat()) if wm else FIRST_START)
            try:
                rows = fetch_district(s, state, district, start, today)
            except WrisError as exc:
                log.error("%s: %s", key, exc)
                failures.append(key)
                continue
            p = run_dir / slug(state) / f"{slug(district)}.json.gz"
            p.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(p, "wt") as f:
                json.dump(rows, f)
            last = max((r.get("dataTime") or "" for r in rows), default=None)
            manifest[key] = {
                "last_data_time": max(filter(None, [last, wm]), default=None),
                "last_fetch": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "rows_last_fetch": len(rows), "fetched_from": start,
            }
            log.info("%s: %d rows since %s", key, len(rows), start)
            if rows:
                frames.append(pd.DataFrame(rows))
            done += 1
            if a.max_districts and done >= a.max_districts:
                break
        if frames:
            counts = merge_state(state, pd.concat(frames, ignore_index=True))
            log.info("%s merged: %s", state, counts)
        MANIFEST.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST.write_text(json.dumps(manifest, indent=1, sort_keys=True))
        if a.max_districts and done >= a.max_districts:
            break

    if failures:
        log.error("%d districts failed: %s", len(failures), failures)
    # Fail loudly if most of the run failed (likely blocked or API changed).
    return 1 if failures and len(failures) > 0.2 * max(done + len(failures), 1) else 0


if __name__ == "__main__":
    sys.exit(main())
