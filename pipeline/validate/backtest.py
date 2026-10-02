"""Phase 6 back-test: run the classification for a past year and compare with
known droughts (docs/plan.md §8, Phase 6 'done when').

Rain axis: SW season (Jun-Sep) departure from our gridded history (IMD's official
district figures for past years were not archived). Groundwater: post-monsoon (NOV)
cycle, which has full manual-network history up to 2023.

Known 2023 declarations used as a reference (news reports, see docs/sources.md):
  Karnataka declared 223 taluks drought-hit by 4 Nov 2023 (nearly the whole state);
  Maharashtra declared 40 talukas on 31 Oct 2023.

Output: notebooks/phase6/backtest_<year>.csv and _summary.json
Usage:  python -m pipeline.validate.backtest [--year 2023]
"""

import argparse
import json
from datetime import date
from pathlib import Path

import pandas as pd

from pipeline.process import groundwater as gw
from pipeline.process.classify import gw_low, quadrant
from pipeline.process.rain import PROC, REF
from pipeline.process.rain_current import category, normal_sum

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "notebooks" / "phase6"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2023)
    a = ap.parse_args(argv)
    y = a.year
    master = pd.read_csv(REF / "district_master.csv")

    mon = pd.read_parquet(PROC / "rain_monthly.parquet")
    act = mon[(mon.year == y) & mon.month.between(6, 9)].groupby("dist_lgd").mm.sum(min_count=1)
    nrm = normal_sum(pd.read_parquet(PROC / "rain_daily_normal.parquet"), date(y, 6, 1), date(y, 9, 30))
    dep = ((act - nrm) / nrm * 100).round()

    c, units = gw.series()
    g = gw.district_status(c, units, master, y, "NOV", live=None)

    rows = []
    for m in master.itertuples():
        d = dep.get(m.dist_lgd)
        cat = category(d) if d is not None and not pd.isna(d) else None
        rs = None if cat is None else cat in {"Deficient", "Large Deficient", "No Rain"}
        gl, why = gw_low(g.get(m.dist_lgd, {}))
        rows.append({"dist_lgd": m.dist_lgd, "district": m.district, "state": m.state,
                     "rain_dep_pct": d, "rain_category": cat, "rain_short": rs,
                     "gw_tier": g[m.dist_lgd]["tier"], "gw_percentile": g[m.dist_lgd].get("percentile"),
                     "gw_low": gl, "quadrant": quadrant(rs, gl)})
    df = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT / f"backtest_{y}.csv", index=False)

    def state(s):
        x = df[df.state == s]
        return {"districts": len(x), "rain_short": int(x.rain_short.fillna(False).sum()),
                "gw_classified": int(x.gw_low.notna().sum()), "gw_low": int(x.gw_low.fillna(False).sum()),
                "quadrants": x.quadrant.value_counts().to_dict()}

    summary = {
        "year": y, "rain": "SW season Jun-Sep, gridded", "groundwater": f"NOV {y} cycle",
        "quadrant_counts": df.quadrant.value_counts(dropna=False).rename(str).to_dict(),
        "gw_tier_counts": df.gw_tier.value_counts().to_dict(),
        "rain_short_districts": int(df.rain_short.fillna(False).sum()),
        "by_state": {s: state(s) for s in ["Karnataka", "Maharashtra", "Telangana", "Andhra Pradesh", "Jharkhand",
                                           "Bihar", "Punjab", "Rajasthan", "Gujarat", "Tamil Nadu"]},
        "hidden_drought": df[df.quadrant == "hidden_drought"][["district", "state", "rain_dep_pct", "gw_percentile"]].to_dict("records"),
    }
    (OUT / f"backtest_{y}_summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps({k: summary[k] for k in ("quadrant_counts", "gw_tier_counts", "rain_short_districts")}, indent=1))
    print(pd.DataFrame(summary["by_state"]).T.to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
