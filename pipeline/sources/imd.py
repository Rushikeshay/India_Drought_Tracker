"""IMD 0.25 deg gridded daily rainfall (Pai et al.), from imdpune.gov.in.

Same endpoints and file layout as imdlib (MIT), but with timeouts and size
checks: imdlib's downloader has no timeout and can hang. See docs/sources.md §1.

File layout: float32 little-endian, [day][lat][lon], lat 6.5..38.5 (129),
lon 66.5..100.0 (135), missing = -999.
"""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import numpy as np
import requests

HIST_URL = "https://imdpune.gov.in/cmpg/Griddata/rainfall.php"
RT_URL = "https://imdpune.gov.in/cmpg/Realtimedata/Rainfall/rain.php"
NLAT, NLON = 129, 135
LATS = np.linspace(6.5, 38.5, NLAT)
LONS = np.linspace(66.5, 100.0, NLON)
DAY_BYTES = NLAT * NLON * 4
RAW = Path(__file__).resolve().parents[2] / "data" / "raw" / "imd"


class ImdError(RuntimeError):
    pass


def _download(url: str, data: dict, dest: Path, expect: set[int], timeout: int, tries: int = 3) -> Path:
    for i in range(tries):
        try:
            r = requests.post(url, data=data, timeout=timeout)
            r.raise_for_status()
            if len(r.content) not in expect:
                raise ImdError(f"{dest.name}: got {len(r.content)} bytes, expected {sorted(expect)}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(r.content)
            tmp.rename(dest)
            return dest
        except (requests.RequestException, ImdError) as exc:
            if i == tries - 1:
                raise ImdError(f"{dest.name}: {exc!r}") from exc
            time.sleep(10 * (i + 1))
    raise AssertionError("unreachable")


def days_in_year(y: int) -> int:
    return 366 if (y % 4 == 0 and y % 100 != 0) or y % 400 == 0 else 365


def year_file(year: int) -> Path:
    p = RAW / "yearly" / f"Rainfall_ind{year}_rfp25.grd"
    n = days_in_year(year) * DAY_BYTES
    if p.exists() and p.stat().st_size == n:
        return p
    return _download(HIST_URL, {"rain": year}, p, {n}, timeout=600)


def day_file(day: date, refresh: bool = False) -> Path:
    p = RAW / "realtime" / f"rain_ind0.25_{day:%y_%m_%d}.grd"
    if p.exists() and p.stat().st_size == DAY_BYTES and not refresh:
        return p
    return _download(RT_URL, {"rain": day.strftime("%d%m%Y")}, p, {DAY_BYTES}, timeout=60)


def read(path: Path) -> np.ndarray:
    """(days, lat, lon) float32 with NaN for missing."""
    a = np.fromfile(path, dtype="<f4")
    if a.size % (NLAT * NLON):
        raise ImdError(f"{path.name}: size {a.size} not a whole number of days")
    a = a.reshape(-1, NLAT, NLON)
    a[a <= -998] = np.nan
    return a
