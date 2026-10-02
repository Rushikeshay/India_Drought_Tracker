"""Name crosswalks from source datasets to LGD district codes.

IN-GRES identifies districts by name only. Match within the same state:
  1. exact match after normalisation        -> method "exact"
  2. a hand-checked alias in ALIASES        -> method "alias"
  3. difflib similarity >= 0.85, unique     -> method "fuzzy" (review these)
  otherwise unmatched (listed, never guessed).

Output: data/reference/crosswalk_ingres.csv
Usage:  python -m pipeline.process.crosswalk
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from pathlib import Path

import pandas as pd

from pipeline.sources import ingres

REPO = Path(__file__).resolve().parents[2]
REF = REPO / "data" / "reference"
FUZZY_MIN = 0.85

# state (as in source) -> {source name: LGD district name}. Hand-checked renames,
# spelling variants and codes. Resolved to LGD codes via district_master.
ALIASES = {
    "ANDHRA PRADESH": {"Sri Potti Sriramulu Nellore": "Spsr Nellore", "Y.S.R Kadapa": "Y.S.R.", "Ananthapuramu": "Anantapur"},
    "ASSAM": {"SIBSAGAR": "Sivasagar", "KAMRUP (M)": "Kamrup Metro"},
    "BIHAR": {"KAIMUR": "Kaimur (Bhabua)", "WEST CHAMPARAN": "Pashchim Champaran",
              "EAST CHAMPARAN": "Purbi Champaran", "PURNEA": "Purnia"},
    "GOA": {"GOA NORTH": "North Goa"},
    "GUJARAT": {"DAHOD": "Dohad", "RANA AND KUTCH": "Kachchh"},
    "HARYANA": {"GURGAON": "Gurugram", "MEWAT": "Nuh"},
    "HIMACHAL PRADESH": {"SLN": "Solan", "KIN": "Kinnaur", "SRM": "Sirmaur", "KNG": "Kangra", "KUL": "Kullu",
                         "MND": "Mandi", "SHM": "Shimla", "BLS": "Bilaspur", "CHM": "Chamba",
                         "LAS": "Lahul And Spiti", "HMP": "Hamirpur"},
    "JAMMU AND KASHMIR": {"Srinagar Hilly Area": "Srinagar", "Kupwarar": "Kupwara", "Barmulla": "Baramulla",
                          "SRINAGAR URBAN": "Srinagar"},
    "JHARKHAND": {"EAST SINGHBHUM": "East Singhbum"},
    "KARNATAKA": {"Bengaluru South": "Ramanagara"},
    "LADAKH": {"LEH": "Leh Ladakh"},
    "MADHYA PRADESH": {"HOSHANGABAD": "Narmadapuram", "KHANDWA": "East Nimar"},
    "MAHARASHTRA": {"Dharashiv": "Osmanabad", "Ahilyanagar": "Ahmednagar", "Ch.Sambhajinagar": "Aurangabad"},
    "ODISHA": {"KEONJHAR": "Kendujhar", "BALASORE": "Baleshwar", "KHURDA": "Khordha", "SUBARNAPUR": "Sonepur"},
    "PUDUCHERRY": {"PUDUCHERRY": "Pondicherry"},
    "PUNJAB": {"Muktsar": "Sri Muktsar Sahib", "Firozpur": "Ferozepur", "SBS Nagar": "Shahid Bhagat Singh Nagar",
               "NAWANSHAHAR": "Shahid Bhagat Singh Nagar", "MOHALI": "S.A.S Nagar"},  # older-edition names
    "MEGHALAYA": {"GREATER SHILLONG": "East Khasi Hills"},
    "RAJASTHAN": {"DHAULPUR": "Dholpur"},
    "TAMILNADU": {"THOOTHUKUDI": "Tuticorin"},
    "UTTAR PRADESH": {"JP NAGAR": "Amroha", "MAUNATH BHANJAN": "Mau", "G.B.NAGAR": "Gautam Buddha Nagar",
                      "LAKHIMPUR KHERI": "Kheri", "SANT RAVIDAS NAGAR": "Bhadohi"},
    "WEST BENGAL": {"NORTH 24 PARGANAS": "24 Paraganas North", "SOUTH 24 PARGANAS": "24 Paraganas South",
                    "KOCH BIHAR": "Coochbehar", "UTTAR DINAJPUR": "Dinajpur Uttar",
                    "DAKSHIN DINAJPUR": "Dinajpur Dakshin", "DARJILING": "Darjeeling", "HUGLI": "Hooghly",
                    "HAORA": "Howrah", "PURBA MEDINIPUR": "Medinipur East", "PASCHIM MEDINIPUR": "Medinipur West"},
    "ANDAMAN AND NICOBAR ISLANDS": {"N & M ANDAMAN": "North And Middle Andaman", "NICOBAR": "Nicobars",
                                    "SOUTH ANDAMAN": "South Andamans"},
}
# Source units that are a PART of an LGD district (several units map to one code).
PART_OF = {("JAMMU AND KASHMIR", "Srinagar Hilly Area"), ("JAMMU AND KASHMIR", "Kupwarar"),
           ("JAMMU AND KASHMIR", "Barmulla"), ("GUJARAT", "RANA AND KUTCH"),
           ("JAMMU AND KASHMIR", "SRINAGAR URBAN"), ("MEGHALAYA", "GREATER SHILLONG")}
# Districts created after our Dec 2023 boundary map: state -> {name: parent on our map or None}.
NOT_ON_MAP = {
    "MADHYA PRADESH": {"PANDHURNA": "Chhindwara", "MAIHAR": "Satna", "MAUGANJ": "Rewa"},
    "ANDHRA PRADESH": {"Markapuram": None, "Polavaram": None},
}
# Pakistan-administered areas reported by IN-GRES; no LGD district.
POK = {("JAMMU AND KASHMIR", "Mirpur"), ("JAMMU AND KASHMIR", "Muzaffarabad")}


def norm(x: str) -> str:
    x = unicodedata.normalize("NFKD", str(x)).encode("ascii", "ignore").decode().lower()
    x = x.replace("&", " and ")
    x = re.sub(r"\b(district|dist)\b", " ", x)
    return re.sub(r"[^a-z0-9]", "", x)


def state_key(x: str) -> str:
    k = norm(x).removesuffix("islands")
    # Dadra & Nagar Haveli and Daman & Diu merged in 2020; sources spell it many ways.
    if k.startswith("dadra") or k.startswith("daman"):
        return "dnhdd"
    return k


def match(master: pd.DataFrame, src: pd.DataFrame, source: str) -> pd.DataFrame:
    """src columns: state, name, plus any source ids to carry through."""
    m = master.assign(sk=master.state.map(state_key), nk=master.district.map(norm))

    def code(sk: str, lgd_name: str) -> int:
        hit = m[(m.sk == sk) & (m.nk == norm(lgd_name))]
        if len(hit) != 1:
            raise ValueError(f"alias target {lgd_name!r} not unique in state {sk}")
        return int(hit.dist_lgd.iloc[0])

    out = []
    for r in src.itertuples(index=False):
        sk, nk = state_key(r.state), norm(r.name)
        cand = m[m.sk == sk]
        lgd, method, score, relation = None, "unmatched", None, "one"
        alias = ALIASES.get(r.state, {}).get(r.name)
        new = NOT_ON_MAP.get(r.state, {})
        if (r.state, r.name) in POK:
            method, relation = "pok", "none"
        elif r.name in new:
            method, relation = "not_on_map", "child_of"
            lgd = code(sk, new[r.name]) if new[r.name] else None
        elif alias:
            lgd, method = code(sk, alias), "alias"
        elif cand.empty:
            method = "unmatched_state"
        elif (hit := cand[cand.nk == nk]).shape[0] == 1:
            lgd, method, score = int(hit.dist_lgd.iloc[0]), "exact", 1.0
        else:
            scores = cand.nk.map(lambda c: difflib.SequenceMatcher(None, nk, c).ratio())
            top = scores.sort_values(ascending=False)
            if len(top) and top.iloc[0] >= FUZZY_MIN and (len(top) == 1 or top.iloc[1] < FUZZY_MIN):
                lgd, method, score = int(cand.loc[top.index[0], "dist_lgd"]), "fuzzy", round(float(top.iloc[0]), 3)
        if (r.state, r.name) in PART_OF:
            relation = "part_of"
        row = r._asdict() | {"source": source, "dist_lgd": lgd, "method": method, "score": score, "relation": relation}
        if lgd is not None:
            row["lgd_name"] = master.loc[master.dist_lgd == lgd, "district"].iloc[0]
        out.append(row)
    return pd.DataFrame(out)


def ingres_crosswalk(master: pd.DataFrame, year: str = ingres.YEAR) -> pd.DataFrame:
    rows = []
    for st in ingres.states(year):
        try:
            ds = ingres.districts(st, year)
        except ingres.IngresError:
            continue  # a state/UT may be absent from an older edition
        for d in ds:
            rows.append({"state": st["locationName"], "name": d["locationName"],
                         "ingres_uuid": d["locationUUID"], "ingres_state_uuid": st["locationUUID"]})
    return match(master, pd.DataFrame(rows), "ingres_" + year)


def main() -> int:
    master = pd.read_csv(REF / "district_master.csv")
    cw = ingres_crosswalk(master)
    cw.to_csv(REF / "crosswalk_ingres.csv", index=False)
    print(cw.method.value_counts().to_string())
    one = cw[cw.relation == "one"].dropna(subset=["dist_lgd"])
    dup = one[one.dist_lgd.duplicated(keep=False)]
    if len(dup):
        raise ValueError(f"LGD codes claimed by more than one IN-GRES district:\n{dup}")
    print("unmatched IN-GRES rows:", cw[cw.method.str.startswith('unmatched')][["state", "name"]].values.tolist())
    missing = master[~master.dist_lgd.isin(cw.dist_lgd)]
    missing[["dist_lgd", "state", "district"]].to_csv(REF / "crosswalk_ingres_unmatched_lgd.csv", index=False)
    print("LGD districts with no IN-GRES row (see crosswalk_ingres_unmatched_lgd.csv):", len(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
