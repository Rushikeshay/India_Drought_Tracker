"""Phase 6: combine the layers into the district status (current tier).

Quadrant (docs/plan.md §7):
                 GW OK      GW low
    Rain OK      fine       hidden_drought
    Rain short   buffered   double_drought
  rain short  = IMD category Deficient, Large Deficient or No Rain for the district's
                current/last season (rain.json headline: IMD official, else gridded)
  GW low      = district percentile <= 20, only for GW tier "full" or "short"
No quadrant (with a reason) when either axis is unknown, or the rain season is
younger than MIN_SEASON_DAYS (e.g. NE-monsoon districts in early October).

Secondary marks: IN-GRES category, hidden block stress, IDM drought class, data ages.

Outputs: web/data/status.json, web/data/status.csv (flat table for the site's list/CSV download)
Usage:   python -m pipeline.process.classify
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
WEB = REPO / "web" / "data"
REF = REPO / "data" / "reference"
RAIN_SHORT = {"Deficient", "Large Deficient", "No Rain"}
GW_TIERS_FOR_QUADRANT = {"full", "short"}
MIN_SEASON_DAYS = 15
QUADRANTS = {(False, False): "fine", (False, True): "hidden_drought",
             (True, False): "buffered", (True, True): "double_drought"}


def rain_short(r: dict) -> tuple[bool | None, str | None]:
    if not r or r.get("category") is None:
        return None, "no_rain_data"
    if r.get("season_days", 999) < MIN_SEASON_DAYS:
        return None, "season_just_started"
    return r["category"] in RAIN_SHORT, None


def gw_low(g: dict) -> tuple[bool | None, str | None]:
    if not g or g.get("tier") not in GW_TIERS_FOR_QUADRANT:
        return None, f"gw_{(g or {}).get('tier', 'missing')}"
    return bool(g["low"]), None


def quadrant(rs: bool | None, gl: bool | None) -> str | None:
    if rs is None or gl is None:
        return None
    return QUADRANTS[(rs, gl)]


def main() -> int:
    rain = json.loads((WEB / "rain.json").read_text())
    gw = json.loads((WEB / "groundwater.json").read_text())
    st = json.loads((WEB / "stress.json").read_text())
    idm = json.loads((WEB / "idm.json").read_text())
    master = pd.read_csv(REF / "district_master.csv")

    out, rows = {}, []
    for m in master.itertuples():
        k = str(m.dist_lgd)
        r, g, s, i = rain["districts"].get(k, {}), gw["districts"].get(k, {}), st["districts"].get(k, {}), idm["districts"].get(k, {})
        rs, r_why = rain_short(r)
        gl, g_why = gw_low(g)
        q = quadrant(rs, gl)
        rec = {
            "quadrant": q, "why_none": None if q else (r_why or g_why),
            "rain": {"season": r.get("season"), "category": r.get("category"), "departure_pct": r.get("departure_pct"),
                     "source": r.get("source"), "season_days": r.get("season_days"), "short": rs},
            "gw": {"tier": g.get("tier"), "percentile": g.get("percentile"), "low": gl,
                   "median_depth_m": g.get("median_depth_m"), "change_vs_last_year_m": g.get("change_vs_last_year_m"),
                   "vs_decadal_mean_m": g.get("vs_decadal_mean_m"), "n_live": g.get("n_live")},
            "stress": {"category": s.get("category"), "stage_pct": s.get("stage_pct"),
                       "hidden_stress": s.get("hidden_stress"), "worst_unit": s.get("worst_unit"), "status": s.get("status")},
            "idm": {"class_of_mean": i.get("class_of_mean"), "pct_in_drought_d0plus": i.get("pct_in_drought_d0plus")},
        }
        out[int(m.dist_lgd)] = rec
        rows.append({"dist_lgd": m.dist_lgd, "district": m.district, "state": m.state, "quadrant": q,
                     "why_none": rec["why_none"], "rain_category": r.get("category"), "rain_departure_pct": r.get("departure_pct"),
                     "rain_source": r.get("source"), "gw_tier": g.get("tier"), "gw_percentile": g.get("percentile"),
                     "gw_change_vs_last_year_m": g.get("change_vs_last_year_m"), "ingres_category": s.get("category"),
                     "ingres_stage_pct": s.get("stage_pct"), "hidden_block_stress": s.get("hidden_stress"),
                     "idm_class": i.get("class_of_mean")})
    counts = pd.Series([v["quadrant"] for v in out.values()]).value_counts(dropna=False)
    why = pd.Series([v["why_none"] for v in out.values() if v["why_none"]]).value_counts()
    doc = {"as_of": {"rain": rain["as_of"], "groundwater_cycle": f"{gw['cycle_months']} {gw['cycle_year']}",
                     "stress_edition": st["edition"], "idm_week": idm["week"]},
           "rules": {"rain_short": sorted(RAIN_SHORT), "gw_low": "district percentile <= 20 (tiers full/short only)",
                     "min_season_days": MIN_SEASON_DAYS},
           "quadrant_counts": {str(k): int(v) for k, v in counts.items()},
           "why_no_quadrant": why.to_dict(), "districts": out}
    WEB.mkdir(parents=True, exist_ok=True)
    (WEB / "status.json").write_text(json.dumps(doc, separators=(",", ":"), default=str))
    pd.DataFrame(rows).to_csv(WEB / "status.csv", index=False)
    print(json.dumps({"quadrants": doc["quadrant_counts"], "why_none": doc["why_no_quadrant"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
