"""Phase 0 probe: IMD gridded 0.25 deg daily rainfall.

Downloads with our own timeouts from the same endpoints imdlib uses
(imdlib's own downloader has no timeout and can hang on a blocked host),
then parses the files with imdlib.open_data / open_real_data.

Tests: historical yearly file (for normals and scenarios), real-time daily
files (for season-to-date; measures publication lag), and reachability of
the mausam.imd.gov.in site used for validation.

Usage: python notebooks/phase0/probe_imd.py [LAT LON]
Default point is Pune city; it is only a probe location, not a district value.
"""

import sys
from datetime import date, timedelta

import imdlib
import numpy as np

from _probe import RAW_DIR, run

HIST_URL = "https://imdpune.gov.in/cmpg/Griddata/rainfall.php"
RT_URL = "https://imdpune.gov.in/cmpg/Realtimedata/Rainfall/rain.php"
YEAR_BYTES = {365: 365 * 129 * 135 * 4, 366: 366 * 129 * 135 * 4}
DAY_BYTES = 129 * 135 * 4
LAT, LON = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) > 2 else (18.52, 73.86)


def body(p):
    d = RAW_DIR / "imd"
    d.mkdir(parents=True, exist_ok=True)
    today = date.today()

    # 1. Newest complete historical year. Record which years the server returns.
    got_year = None
    for yr in (today.year - 1, today.year - 2):
        r = p.http(f"hist_{yr}", "POST", HIST_URL, data={"rain": yr}, timeout=300, required=False)
        if r is None or not r.ok:
            continue
        n = len(r.content)
        p.note(f"hist_{yr}_bytes", n)
        if n in YEAR_BYTES.values():
            (d / f"Rainfall_ind{yr}_rfp25.grd").write_bytes(r.content)
            got_year = yr
            break
        p.note(f"hist_{yr}_head", r.content[:200].decode(errors="replace"))
    if got_year is None:
        raise RuntimeError("no complete historical year file returned")
    p.note("latest_full_historical_year", got_year)

    ds = imdlib.open_data("rain", got_year, got_year, None, str(d)).get_xarray()
    cell = ds["rain"].sel(lat=LAT, lon=LON, method="nearest")
    p.note("grid_cell", [float(cell.lat), float(cell.lon)])
    jjas = cell.sel(time=slice(f"{got_year}-06-01", f"{got_year}-09-30"))
    p.note(f"jjas_{got_year}_mm_at_cell", round(float(jjas.sum()), 1))
    p.note("dims", dict(ds.sizes))

    # 2. Real-time daily files: walk back from today to find the newest one.
    latest = None
    for back in range(0, 10):
        day = today - timedelta(days=back)
        r = p.http(f"rt_{day}", "POST", RT_URL, data={"rain": day.strftime("%d%m%Y")}, timeout=60, required=False)
        if r is None or not r.ok:
            continue
        if len(r.content) == DAY_BYTES:
            (d / f"rain_ind0.25_{day.strftime('%y_%m_%d')}.grd").write_bytes(r.content)
            latest = latest or day
        else:
            p.note(f"rt_{day}_bytes", len(r.content))
    if latest is None:
        raise RuntimeError("no real-time daily file in the last 10 days")
    p.note("latest_realtime_day", str(latest))
    p.note("realtime_lag_days", (today - latest).days)
    rt = imdlib.open_real_data("rain", str(latest), str(latest), str(d)).get_xarray()
    v = rt["rain"].sel(lat=LAT, lon=LON, method="nearest")
    p.note(f"rt_{latest}_mm_at_cell", round(float(v.values.squeeze()), 1))
    arr = rt["rain"].values
    p.note("rt_valid_cells", int(np.sum(arr > -998)))

    # 3. Validation site reachability (district departure pages live here)
    p.http("mausam_home", "GET", "https://mausam.imd.gov.in/", timeout=60, required=False)


if __name__ == "__main__":
    run("imd", body)
