"""IN-GRES groundwater stress for every published edition, so the status history can
show the assessment that was current at each snapshot date.

Editions served by the API (probed 2026-10-01): 2016-2017, 2019-2020, 2021-2022 ...
2025-2026. District level only (relation "one" in each edition's crosswalk); block level
("worst block") exists for the current edition only. Figures are used as published.

Output: data/processed/ingres_editions.csv   edition, end_year, dist_lgd, category, stage_pct
Usage:  python -m pipeline.process.stress_history
"""

from pathlib import Path

import pandas as pd

from pipeline.process.crosswalk import ingres_crosswalk
from pipeline.process.stress import fields
from pipeline.sources import ingres

REPO = Path(__file__).resolve().parents[2]
REF = REPO / "data" / "reference"
PROC = REPO / "data" / "processed"
# 2016-2017 is served but excluded: 446 of its 668 district rows carry category "hilly",
# which is not plausible as a district-level assessment (checked 2026-10-01).
EDITIONS = ["2019-2020", "2021-2022", "2022-2023", "2023-2024", "2024-2025", "2025-2026"]


def edition_for(year: int, month: int) -> str | None:
    """Latest edition whose assessment year has ended by the snapshot (end year <= snapshot year)."""
    ok = [e for e in EDITIONS if int(e[-4:]) <= year]
    return ok[-1] if ok else None


def main() -> int:
    master = pd.read_csv(REF / "district_master.csv")
    rows = []
    for ed in EDITIONS:
        cw = ingres_crosswalk(master, ed)
        cw.to_csv(REF / f"crosswalk_ingres_{ed}.csv", index=False)
        by = {}
        for st in ingres.states(ed):
            try:
                for d in ingres.districts(st, ed):
                    by[(st["locationName"], d["locationName"])] = d
            except ingres.IngresError:
                continue
        one = cw[(cw.relation == "one") & cw.dist_lgd.notna()]
        for r in one.itertuples():
            f = fields(by[(r.state, r.name)])
            rows.append({"edition": ed, "end_year": int(ed[-4:]), "dist_lgd": int(r.dist_lgd),
                         "category": f["category"], "stage_pct": f["stage_pct"], "method": r.method})
        print(ed, "districts:", len(one), "unmatched:", int(cw.method.str.startswith("unmatched").sum()))
    df = pd.DataFrame(rows)
    dup = df[df.duplicated(["edition", "dist_lgd"], keep=False)]
    if len(dup):
        print("districts matched by >1 IN-GRES row (kept first):", dup[["edition", "dist_lgd"]].drop_duplicates().values.tolist())
    # IN-GRES lists some districts twice in older editions (e.g. Himachal "SHIMLA" and code "SHM"):
    # prefer an exact full-name match, then a row that has a category.
    rank = {"exact": 0, "alias": 1, "fuzzy": 2}
    df = (df.assign(_r=df.method.map(rank).fillna(3), _c=df.category.isna())
            .sort_values(["edition", "dist_lgd", "_r", "_c"]).drop_duplicates(["edition", "dist_lgd"])
            .drop(columns=["_r", "_c"]))
    PROC.mkdir(parents=True, exist_ok=True)
    df.to_csv(PROC / "ingres_editions.csv", index=False)
    print(df.groupby("edition").category.value_counts().unstack(fill_value=0).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
