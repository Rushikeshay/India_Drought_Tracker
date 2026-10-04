"""Last check before the daily run publishes web/data: the files must be valid JSON and
cover roughly as many districts as they should. A failing check keeps the previous
version of the site online (the workflow does not commit web/data).

The floors sit well below today's coverage (rain 779, drought index 775, stress 719,
groundwater 436 of 783 districts), so they catch a broken source or a bad join, not
ordinary day-to-day movement.

Usage: python -m pipeline.validate.publish
"""

from __future__ import annotations

import json
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web" / "data"
N_DISTRICTS = 783
FLOORS = {"rain": 700, "idm": 700, "stress": 650, "gw": 250}
MIN_SNAPSHOTS = 107


def _strict(path: Path):
    def bad(x):
        raise ValueError(f"{path.name}: {x} is not valid JSON")
    return json.loads(path.read_text(), parse_constant=bad)


def status_problems(doc: dict) -> list[str]:
    d = doc.get("districts", {})
    out = []
    if len(d) != N_DISTRICTS:
        out.append(f"status.json has {len(d)} districts, expected {N_DISTRICTS}")
    have = {
        "rain": sum(1 for r in d.values() if (r.get("rain") or {}).get("category")),
        "idm": sum(1 for r in d.values() if (r.get("idm") or {}).get("class_of_mean")),
        "stress": sum(1 for r in d.values() if (r.get("stress") or {}).get("status") == "assessed"),
        "gw": sum(1 for r in d.values() if (r.get("gw") or {}).get("tier") not in (None, "insufficient")),
    }
    out += [f"{k}: only {have[k]} districts have data (floor {n})" for k, n in FLOORS.items() if have[k] < n]
    if not all((doc.get("as_of") or {}).get(k) for k in ("rain", "groundwater_cycle", "stress_edition", "idm_week")):
        out.append("status.json as_of is incomplete")
    return out


def problems(web: Path = WEB) -> list[str]:
    out = []
    docs = {}
    for name in ("status.json", "rain.json", "groundwater.json", "gw_history.json", "idm.json", "stress.json", "history/index.json"):
        try:
            docs[name] = _strict(web / name)
        except (OSError, ValueError) as exc:
            out.append(f"{name}: {exc}")
    if "status.json" in docs:
        out += status_problems(docs["status.json"])
    idx = docs.get("history/index.json")
    if idx:
        snaps = idx.get("snapshots", [])
        if len(snaps) < MIN_SNAPSHOTS:
            out.append(f"history has {len(snaps)} snapshots, expected at least {MIN_SNAPSHOTS}")
        missing = [s for s in snaps if not (web / "history" / f"s_{s}.json").exists()]
        if missing:
            out.append(f"history snapshot files missing: {missing[:5]}")
        n_d = len(list((web / "history").glob("d_*.json")))
        if n_d != N_DISTRICTS:
            out.append(f"history has {n_d} district files, expected {N_DISTRICTS}")
    return out


if __name__ == "__main__":
    p = problems()
    print("\n".join(p) if p else "publish check: OK")
    raise SystemExit(1 if p else 0)
