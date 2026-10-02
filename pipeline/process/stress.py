"""Phase 4: IN-GRES groundwater stress (Dynamic Ground Water Resources 2025-26).

IN-GRES's own figures are used as published (stage of extraction %, category);
nothing is recomputed. Joined to LGD districts through data/reference/crosswalk_ingres.csv:
  relation "one"       the district's headline figures
  relation "part_of"   an extra IN-GRES unit inside the district (e.g. Rann of Kutch in Kachchh)
  relation "child_of"  a new district IN-GRES assesses separately but our map still includes
                       (e.g. Pandhurna inside Chhindwara); listed, not merged
Districts with no IN-GRES row are marked "not_in_ingres" (carved-out districts still
counted inside their parent, or areas IN-GRES does not assess).

Block / taluk / mandal / firka level comes from the district drill-down call.

Outputs
  web/data/stress.json
  data/processed/ingres_2025_26_districts.csv, ingres_2025_26_units.csv
Usage: python -m pipeline.process.stress
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from pipeline.sources import ingres

REPO = Path(__file__).resolve().parents[2]
REF = REPO / "data" / "reference"
PROC = REPO / "data" / "processed"
WEB = REPO / "web" / "data"
LABEL = {"safe": "Safe", "semi_critical": "Semi-critical", "critical": "Critical",
         "over_exploited": "Over-exploited", "salinity": "Saline", "Hilly Area": "Hilly area"}
STRESSED = {"Critical", "Over-exploited"}
RANK = {"Safe": 0, "Semi-critical": 1, "Critical": 2, "Over-exploited": 3}

log = logging.getLogger("stress")


def _tot(v):
    if isinstance(v, dict):
        v = v.get("total")
    return round(float(v), 2) if isinstance(v, (int, float)) else None


def fields(r: dict) -> dict:
    cat = r.get("category")
    cat = cat.get("total") if isinstance(cat, dict) else cat
    pq = r.get("category", {}).get("poor_quality") if isinstance(r.get("category"), dict) else None
    return {
        "name": r.get("locationName"),
        "category": LABEL.get(cat, cat),
        "stage_pct": _tot(r.get("stageOfExtraction")),
        "recharge_ham": _tot((r.get("rechargeData") or {}).get("total")),
        "extractable_ham": _tot(r.get("totalGWAvailability")),
        "extraction_ham": _tot((r.get("draftData") or {}).get("total")),
        "poor_quality_category": LABEL.get(pq, pq),
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cw = pd.read_csv(REF / "crosswalk_ingres.csv")
    master = pd.read_csv(REF / "district_master.csv")
    states = {s["locationName"]: s for s in ingres.states()}
    by_name = {}
    for sname, st in states.items():
        for d in ingres.districts(st):
            by_name[(sname, d["locationName"])] = d

    drows, urows = [], []
    for r in cw.itertuples():
        d = by_name.get((r.state, r.name))
        if d is None:
            log.warning("no IN-GRES row for %s / %s", r.state, r.name)
            continue
        f = fields(d)
        drows.append({"state": r.state, "ingres_name": r.name, "dist_lgd": r.dist_lgd, "relation": r.relation,
                      "method": r.method} | f)
        try:
            units = ingres.units(d, states[r.state])
        except ingres.IngresError as exc:
            log.error("units failed for %s / %s: %s", r.state, r.name, exc)
            units = []
        for u in units:
            urows.append({"state": r.state, "ingres_district": r.name, "dist_lgd": r.dist_lgd} | fields(u))
    D = pd.DataFrame(drows)
    U = pd.DataFrame(urows)
    PROC.mkdir(parents=True, exist_ok=True)
    D.to_csv(PROC / "ingres_2025_26_districts.csv", index=False)
    U.to_csv(PROC / "ingres_2025_26_units.csv", index=False)
    log.info("IN-GRES: %d district rows, %d units", len(D), len(U))

    out = {}
    for code in master.dist_lgd:
        rows = D[D.dist_lgd == code]
        head = rows[rows.relation == "one"]
        extra = rows[rows.relation.isin(["part_of", "child_of"])]
        if head.empty and extra.empty:
            out[int(code)] = {"status": "not_in_ingres"}
            continue
        rec = {"status": "assessed"}
        if len(head):
            h = head.iloc[0]
            rec.update({k: (None if pd.isna(h[k]) else h[k]) for k in
                        ("ingres_name", "category", "stage_pct", "recharge_ham", "extractable_ham",
                         "extraction_ham", "poor_quality_category")})
        else:
            rec["status"] = "only_sub_units"
        u = U[U.dist_lgd == code]
        if len(u):
            cats = u.category.fillna("Not given").value_counts().to_dict()
            rated = u[u.category.isin(RANK.keys())].copy()
            rec["units"] = {"n": int(len(u)), "by_category": cats}
            if len(rated):
                rated["rk"] = rated.category.map(RANK)
                w = rated.sort_values(["rk", "stage_pct"], ascending=False).iloc[0]
                rec["worst_unit"] = {"name": w["name"], "category": w.category, "stage_pct": w.stage_pct,
                                     "in": w.ingres_district}
            rec["any_unit_critical_or_oe"] = bool(u.category.isin(STRESSED).any())
            rec["hidden_stress"] = bool(rec["any_unit_critical_or_oe"] and rec.get("category") not in STRESSED)
        if len(extra):
            rec["extra_ingres_units"] = [
                {"name": e.ingres_name, "relation": e.relation, "category": e.category, "stage_pct": e.stage_pct}
                for e in extra.itertuples()]
        out[int(code)] = rec

    status = pd.Series([v["status"] for v in out.values()]).value_counts().to_dict()
    cats = pd.Series([v.get("category") for v in out.values()]).value_counts(dropna=False).to_dict()
    doc = {"edition": "2025-2026 (IN-GRES Dynamic Ground Water Resources)",
           "source": "CGWB & IIT Hyderabad, ingres.iith.ac.in; figures as published",
           "units": "ham = hectare-metres; stage_pct = extraction / extractable resource x 100",
           "status_counts": status, "category_counts": {str(k): v for k, v in cats.items()},
           "unmatched_ingres_rows": cw[cw.method.str.startswith("unmatched")][["state", "name"]].values.tolist(),
           "districts": out}
    WEB.mkdir(parents=True, exist_ok=True)
    (WEB / "stress.json").write_text(json.dumps(doc, separators=(",", ":"), default=str))
    log.info("status %s; categories %s; hidden stress in %d districts", status, cats,
             sum(v.get("hidden_stress", False) for v in out.values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
