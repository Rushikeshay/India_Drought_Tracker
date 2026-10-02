"""Parse IMD's district rainfall PDFs (mausam.imd.gov.in/Rainfall/).

DISTRICT_RAINFALL_DISTRIBUTION_COUNTRY_INDIA_cd.pdf
    districts grouped by met subdivision and state -> IMD district list with
    subdivision + state (also used to check the NE-monsoon list)
DISTRICT_RAINFALL_DEPARTURECUMULATIVE_COUNTRY_INDIA_c.pdf
    week-by-week cumulative % departure since Jun 1; the last column is the
    season-to-date departure at the end of the period.

Output: data/reference/imd_districts.csv (IMD name, subdivision, state, dist_lgd)
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import requests
from pypdf import PdfReader

from pipeline.process.crosswalk import match

REPO = Path(__file__).resolve().parents[2]
DIR = REPO / "data" / "raw" / "imd" / "validation"
REF = REPO / "data" / "reference"
BASE = "https://mausam.imd.gov.in/Rainfall/"
CD = "DISTRICT_RAINFALL_DISTRIBUTION_COUNTRY_INDIA_cd.pdf"
CUM = "DISTRICT_RAINFALL_DEPARTURECUMULATIVE_COUNTRY_INDIA_c.pdf"

# IMD's 36 met subdivisions -> the state to assume until a state heading appears
# (None where the subdivision spans several states and always has state headings).
SUBDIVISIONS = {
    "ANDAMAN & NICOBAR ISLANDS": "ANDAMAN & NICOBAR ISLANDS", "ARUNACHAL PRADESH": "ARUNACHAL PRADESH",
    "ASSAM & MEGHALAYA": None, "NMMT": None, "SHWB & SIKKIM": None, "GANGETIC WEST BENGAL": "WEST BENGAL",
    "ODISHA": "ODISHA", "JHARKHAND": "JHARKHAND", "BIHAR": "BIHAR",
    "WEST UTTAR PRADESH": "UTTAR PRADESH", "EAST UTTAR PRADESH": "UTTAR PRADESH", "UTTARAKHAND": "UTTARAKHAND",
    "DELHI AND HARYANA AND CHANDIGARH": None, "PUNJAB": "PUNJAB", "HIMACHAL PRADESH": "HIMACHAL PRADESH",
    "JAMMU & KASHMIR AND LADAKH": None, "EAST RAJASTHAN": "RAJASTHAN", "WEST RAJASTHAN": "RAJASTHAN",
    "WEST MADHYA PRADESH": "MADHYA PRADESH", "EAST MADHYA PRADESH": "MADHYA PRADESH",
    "GUJARAT REGION": None, "SAURASHTRA & KUTCH": None, "KONKAN & GOA": None,
    "MADHYA MAHARASHTRA": "MAHARASHTRA", "MARATHWADA": "MAHARASHTRA", "VIDARBHA": "MAHARASHTRA",
    "CHHATTISGARH": "CHHATTISGARH", "COASTAL ANDHRA PRADESH & YANAM": None, "RAYALASEEMA": "ANDHRA PRADESH",
    "TELANGANA": "TELANGANA", "TAMILNADU & PUDUCHERRY & KARAIKAL": None,
    "COASTAL KARNATAKA": "KARNATAKA", "NORTHERN INTERIOR KARNATAKA": "KARNATAKA",
    "SOUTHERN INTERIOR KARNATAKA": "KARNATAKA", "KERALA & MAHE": None, "LAKSHADWEEP": "LAKSHADWEEP",
}
# IMD district spelling -> LGD district name, per state (hand-checked).
IMD_ALIASES: dict[str, dict[str, str]] = {
    "ASSAM": {"KAMRUP METROPOLITAN": "Kamrup Metro", "KAMRUP RURAL": "Kamrup",
              "SOUTH SALMARA": "South Salmara Mancachar", "SRIBHUMI": "Karimganj"},  # Karimganj renamed Sribhumi 2024
    "WEST BENGAL": {"NORTH DINAJPUR": "Dinajpur Uttar", "SOUTH DINAJPUR": "Dinajpur Dakshin",
                    "EAST MIDNAPORE": "Medinipur East", "WEST MIDNAPORE": "Medinipur West",
                    "NORTH 24 PARGANAS": "24 Paraganas North", "SOUTH 24 PARGANAS": "24 Paraganas South"},
    "ODISHA": {"KEONJHARGARH": "Kendujhar", "NAWAPARA": "Nuapada"},
    "BIHAR": {"BHABUA": "Kaimur (Bhabua)"},
    "UTTAR PRADESH": {"BADAUN": "Budaun", "KANPUR CITY": "Kanpur Nagar", "RAE BAREILLY": "Rae Bareli"},
    "UTTARAKHAND": {"GARHWAL PAURI": "Pauri Garhwal", "GARHWAL TEHRI": "Tehri Garhwal"},
    "DELHI": {f"{d.upper()} DELHI": d for d in
              ["Central", "East", "North", "North East", "North West", "South", "South East", "South West", "West"]},
    "PUNJAB": {"MUKTSAR": "Sri Muktsar Sahib", "SAS NAGAR (MOHALI)": "S.A.S Nagar", "SBS NAGAR": "Shahid Bhagat Singh Nagar"},
    "JAMMU & KASHMIR": {"BADGAM": "Budgam"},
    "LADAKH": {"LADAKH (LEH)": "Leh Ladakh"},
    "GUJARAT": {"MEHSANA": "Mahesana", "KUTCH": "Kachchh"},
    "MAHARASHTRA": {"MUMBAI CITY": "Mumbai", "CHHATRAPATI SAMBHAJINAGAR": "Aurangabad", "DHARASHIV": "Osmanabad",
                    "AMRAOTI": "Amravati", "YEOTMAL": "Yavatmal"},
    "CHHATTISGARH": {"JANJGIR": "Janjgir-Champa", "KORIYA": "Korea",
                     "KHAIRAGARH CHH GANDAI": "Khairgarh Chhuikhadan Gandai",
                     "MANENDRAGARH BHARATPUR": "Manendragarh Chirimiri Bharatpur",
                     "MOHALA MANPUR CHOWKI": "Mohla Manpur Ambagarh Chouki"},
    "ANDHRA PRADESH": {"DR B R AMBEDKAR KONASEEMA": "Konaseema"},
    "TELANGANA": {"B. KOTHAGUDEM": "Bhadradri Kothagudem", "J. BHUPALPALLY": "Jayashankar Bhupalapally",
                  "KUMARAM BHEEM": "Kumuram Bheem Asifabad", "M. MALKAJGIRI": "Medchal Malkajgiri",
                  "Y. BHUVANAGIRI": "Yadadri Bhuvanagiri"},
    "TAMIL NADU": {"NILGIRIS": "The Nilgiris", "THOOTHUKUDI": "Tuticorin"},
    "KERALA": {"WYNAD": "Wayanad"},
}

NUM = re.compile(r"^-?\d+(\.\d+)?%?$")


def fetch(name: str) -> Path:
    p = DIR / name
    r = requests.get(BASE + name, timeout=180, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    DIR.mkdir(parents=True, exist_ok=True)
    p.write_bytes(r.content)
    return p


def lines(path: Path) -> list[str]:
    return [ln for pg in PdfReader(path).pages for ln in pg.extract_text().splitlines()]


def period(path: Path) -> str:
    for ln in lines(path)[:8]:
        if "PERIOD" in ln.upper():
            return ln.strip()
    return ""


def district_groups(path: Path) -> pd.DataFrame:
    rows, sub, state = [], None, None
    for ln in lines(path):
        s = ln.strip()
        if not s or s.startswith(("India Meteorological", "Hydromet", "DISTRICT RAINFALL", "DAY:", "S.No")):
            continue
        m = re.match(r"^(\d+)\s+(.*)$", s)
        if m and ln[:1] != " ":
            toks = m.group(2).split()
            name = []
            for k, t in enumerate(toks):
                nxt = toks[k + 1] if k + 1 < len(toks) else ""
                if (NUM.match(t) or t == "ND") and not (t.isdigit() and nxt.isalpha() and nxt.isupper() and nxt != "ND"):
                    break
                name.append(t)
            rows.append({"imd_name": " ".join(name), "subdivision": sub, "state": state})
            continue
        head = re.split(r"\s+-?\d", s)[0].strip()
        if head in SUBDIVISIONS:
            sub, state = head, SUBDIVISIONS[head]
        else:
            state = head.replace("(UT)", "").strip()
    return pd.DataFrame(rows)


def cumulative_last(path: Path) -> pd.DataFrame:
    """Last column of the week-by-week cumulative departure table."""
    text = "\n".join(lines(path))
    name = r"[A-Z][A-Z0-9 .&()'\-]*?[A-Z)]"
    pat = re.compile(rf"(?m)^(\d+)\s+({name}(?:\n{name})*)\s+((?:(?:-?\d+|ND)[ \t]+)+(?:-?\d+|ND))[ \t]*$")
    out = []
    for m in pat.finditer(text):
        vals = m.group(3).split()
        last = vals[-1]
        out.append({"sno": int(m.group(1)), "imd_name": " ".join(m.group(2).split()),
                    "imd_dep_pct": None if last == "ND" else int(last), "n_weeks": len(vals)})
    return pd.DataFrame(out)


def imd_crosswalk(groups: pd.DataFrame) -> pd.DataFrame:
    master = pd.read_csv(REF / "district_master.csv")
    src = groups.rename(columns={"imd_name": "name"})[["state", "name", "subdivision"]]
    src["state"] = src.state.str.replace("TAMILNADU", "TAMIL NADU")
    # reuse the IN-GRES matcher with IMD-specific aliases
    from pipeline.process import crosswalk as cw
    saved = cw.ALIASES
    cw.ALIASES = {k: {**saved.get(k, {}), **IMD_ALIASES.get(k, {})} for k in set(saved) | set(IMD_ALIASES)}
    try:
        return match(master, src, "imd")
    finally:
        cw.ALIASES = saved
