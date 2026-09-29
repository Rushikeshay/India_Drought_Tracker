"""Phase 0 probe: IIT Gandhinagar India Drought Monitor (cross-check layer).

Repo github.com/wcl-iitgn/IndianDroughtMonitor has NO license file. This probe
only tests access and format; do not republish its data until the lab agrees
(docs/plan.md §4.4, §10).

Files: data/Current_CDI.txt and data/*_{7,15,30}day.txt are whitespace text grids
("lat lon value"); data/districts/district-stats.json is per-district drought %.
"""

import io
import os
from datetime import datetime, timezone

import pandas as pd

from _probe import run

REPO = "wcl-iitgn/IndianDroughtMonitor"
RAW = f"https://raw.githubusercontent.com/{REPO}/main"
API = f"https://api.github.com/repos/{REPO}"


def body(p):
    if os.environ.get("GITHUB_TOKEN"):  # avoids the 60/h anonymous limit on runners
        p.session.headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"

    r = p.http("repo_meta", "GET", API, timeout=30)
    j = r.json()
    p.note("license", j.get("license"))
    p.note("pushed_at", j.get("pushed_at"))

    r = p.http("cdi_last_commit", "GET", f"{API}/commits", params={"path": "data/Current_CDI.txt", "per_page": 1}, timeout=30)
    c = r.json()[0]["commit"]["committer"]["date"]
    p.note("cdi_last_commit", c)
    p.note("cdi_age_days", (datetime.now(timezone.utc) - datetime.fromisoformat(c.replace("Z", "+00:00"))).days)

    r = p.http("current_cdi", "GET", f"{RAW}/data/Current_CDI.txt", timeout=60)
    p.save_raw("idm_Current_CDI.txt", r.content)
    g = pd.read_csv(io.BytesIO(r.content), sep=r"\s+", header=None, names=["lat", "lon", "value"])
    p.note("cdi_cells", len(g))
    p.note("cdi_grid_step", [float(g.lat.drop_duplicates().sort_values().diff().median()), float(g.lon.drop_duplicates().sort_values().diff().median())])
    p.note("cdi_value_range", [float(g.value.min()), float(g.value.max())])

    r = p.http("summary_latest", "GET", f"{RAW}/data/summary_latest.txt", timeout=30, required=False)
    if r is not None and r.ok:
        p.note("summary_head", r.text[:400])

    r = p.http("district_stats", "GET", f"{RAW}/data/districts/district-stats.json", timeout=60)
    p.save_raw("idm_district-stats.json", r.content)
    d = r.json()
    p.note("district_stats_type", type(d).__name__)
    if isinstance(d, dict):
        p.note("district_stats_keys", list(d.keys())[:10])
        p.note("district_stats_week_ending", d.get("week_ending"))
        rows = d.get("districts") or []
        p.note("district_stats_count", len(rows))
        p.note("district_stats_sample", rows[:1])
    else:
        p.note("district_stats_len", len(d))
        p.note("district_stats_sample", str(d[:2])[:400])


if __name__ == "__main__":
    run("idm", body)
