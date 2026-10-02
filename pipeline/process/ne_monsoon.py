"""Districts whose main rainy season is the NE monsoon (Oct-Dec).

IMD reports NE-monsoon rainfall for five meteorological subdivisions:
Coastal Andhra Pradesh & Yanam, Rayalaseema, Tamil Nadu-Puducherry-Karaikal,
South Interior Karnataka, and Kerala & Mahe. Together, Coastal AP and Rayalaseema
cover all of Andhra Pradesh.

South Interior Karnataka (SIK) membership below follows IMD's subdivision
definition. TODO: verify against IMD's district-to-subdivision list when the
validation PDF can be parsed.

Output: data/reference/ne_monsoon_districts.csv
"""

from pathlib import Path

import pandas as pd

REF = Path(__file__).resolve().parents[2] / "data" / "reference"
WHOLE_STATES = {"Andhra Pradesh": "Coastal AP / Rayalaseema", "Tamil Nadu": "Tamil Nadu, Puducherry & Karaikal",
                "Puducherry": "Tamil Nadu, Puducherry & Karaikal (Yanam: Coastal AP; Mahe: Kerala)",
                "Kerala": "Kerala & Mahe"}
SIK = ["Bengaluru Rural", "Bengaluru Urban", "Chamarajanagara", "Chikkaballapura", "Chikkamagaluru",
       "Chitradurga", "Davangere", "Hassan", "Kodagu", "Kolar", "Mandya", "Mysuru", "Ramanagara",
       "Shivamogga", "Tumakuru"]


def main() -> int:
    m = pd.read_csv(REF / "district_master.csv")
    a = m[m.state.isin(WHOLE_STATES)].assign(subdivision=lambda d: d.state.map(WHOLE_STATES))
    k = m[(m.state == "Karnataka") & m.district.isin(SIK)].assign(subdivision="South Interior Karnataka")
    missing = set(SIK) - set(k.district)
    if missing:
        raise ValueError(f"SIK names not in master: {missing}")
    out = pd.concat([a, k])[["dist_lgd", "state", "district", "subdivision"]].sort_values(["state", "district"])
    out.to_csv(REF / "ne_monsoon_districts.csv", index=False)
    print(f"{len(out)} NE-monsoon districts:", out.groupby("state").size().to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
