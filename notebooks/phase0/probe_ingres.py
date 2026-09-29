"""Phase 0 probe: IN-GRES Dynamic Ground Water Resources assessment.

Payload shape adapted from neer-vazhvu's build_ingres_gwr.py
(github.com/SundareshPrasanna/neer-vazhvu, MIT License, (c) its authors).
Keys are lowercase, locname has no spaces, parentuuid is required: a wrong
parentuuid returns HTTP 200 with an empty table, so we check row counts.

Usage: python notebooks/phase0/probe_ingres.py [STATE] [DISTRICT]
"""

import json
import sys
from collections import Counter

from _probe import run

API = "https://ingres.iith.ac.in/api/gec/getBusinessDataForUserOpen"
INDIA_UUID = "ffce954d-24e1-494b-ba7e-0931d8ad6085"
STATE = sys.argv[1] if len(sys.argv) > 1 else "MAHARASHTRA"
DISTRICT = sys.argv[2] if len(sys.argv) > 2 else "PUNE"
# Newest first; we record which editions the API actually serves.
YEARS = ["2025-2026", "2024-2025", "2023-2024"]


def payload(locname, loctype, locuuid, parentuuid, year, category=None):
    return {
        "parentLocName": "INDIA", "locname": locname, "loctype": loctype, "view": "admin",
        "locuuid": locuuid, "year": year, "computationType": "normal", "component": "recharge",
        "period": "annual", "category": category, "stateuuid": None,
        "verificationStatus": 1, "approvalLevel": 1, "parentuuid": parentuuid,
    }


def name_of(row):
    return row.get("locationName") or row.get("locname") or row.get("name")


def cat_of(row):
    c = row.get("category")
    return c.get("total") if isinstance(c, dict) else c


def body(p):
    # 1. Country call -> all states with UUIDs; also tells us which edition exists.
    states, year = None, None
    for y in YEARS:
        r = p.http(f"country_{y}", "POST", API, json=payload("INDIA", "COUNTRY", INDIA_UUID, INDIA_UUID, y, "safe"), timeout=120)
        rows = r.json()
        if isinstance(rows, list) and len(rows) > 1:
            states, year = rows, y
            p.save_raw(f"ingres_country_{y}.json", r.content)
            break
        p.note(f"country_{y}_rows", len(rows) if isinstance(rows, list) else type(rows).__name__)
    if not states:
        raise RuntimeError("country-level call returned no states for any year tried")
    p.note("latest_edition_served", year)
    p.note("row_keys", sorted(states[0].keys()))
    p.note("state_count", len(states))
    uuids = {name_of(s): s.get("locationUUID") for s in states}
    p.note("states", uuids)
    st_uuid = next((u for n, u in uuids.items() if n and n.replace(" ", "").upper() == STATE), None)
    if not st_uuid:
        raise RuntimeError(f"{STATE} not in country response")

    # 2. State call -> districts
    r = p.http("state_districts", "POST", API, json=payload(STATE, "STATE", st_uuid, INDIA_UUID, year, "safe"), timeout=120)
    dists = r.json()
    p.save_raw(f"ingres_{STATE}_{year}.json", r.content)
    if not isinstance(dists, list) or len(dists) < 2:
        raise RuntimeError(f"state call returned {dists!r:.200}")
    p.note("district_count", len(dists))
    p.note("district_categories", dict(Counter(cat_of(d) for d in dists)))
    d = next((d for d in dists if (name_of(d) or "").upper() == DISTRICT), None)
    if not d:
        raise RuntimeError(f"{DISTRICT} not in {STATE}")
    p.note("district_row", {k: d.get(k) for k in ("locationName", "locationUUID", "category", "stageOfExtraction")})

    # 3. District call -> blocks / assessment units (catches Pune-Safe / Shirur-Critical cases)
    r = p.http("district_units", "POST", API, json=payload(DISTRICT, "DISTRICT", d["locationUUID"], st_uuid, year), timeout=120)
    units = r.json()
    p.save_raw(f"ingres_{STATE}_{DISTRICT}_{year}.json", r.content)
    if not isinstance(units, list) or len(units) < 2:
        raise RuntimeError(f"district call returned {json.dumps(units)[:200]}")
    p.note("unit_count", len(units))
    p.note("unit_categories", {name_of(u): cat_of(u) for u in units})
    p.note("unit_stage_of_extraction", {name_of(u): (u.get("stageOfExtraction") or {}).get("total") if isinstance(u.get("stageOfExtraction"), dict) else u.get("stageOfExtraction") for u in units})


if __name__ == "__main__":
    run("ingres", body)
