"""IN-GRES Dynamic Ground Water Resources assessment (CGWB + IIT Hyderabad).

Payload shape adapted from neer-vazhvu's build_ingres_gwr.py
(github.com/SundareshPrasanna/neer-vazhvu, MIT License). Keys are lowercase,
locname has no spaces, and parentuuid is required: a wrong parentuuid returns
HTTP 200 with an empty table. Every response also carries a "total" row,
which callers must drop. See docs/sources.md §2.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

API = "https://ingres.iith.ac.in/api/gec/getBusinessDataForUserOpen"
INDIA_UUID = "ffce954d-24e1-494b-ba7e-0931d8ad6085"
YEAR = "2025-2026"
RAW = Path(__file__).resolve().parents[2] / "data" / "raw" / "ingres"


class IngresError(RuntimeError):
    pass


def _payload(locname, loctype, locuuid, parentuuid, year, category=None):
    return {
        "parentLocName": "INDIA", "locname": locname.replace(" ", ""), "loctype": loctype, "view": "admin",
        "locuuid": locuuid, "year": year, "computationType": "normal", "component": "recharge",
        "period": "annual", "category": category, "stateuuid": None,
        "verificationStatus": 1, "approvalLevel": 1, "parentuuid": parentuuid,
    }


def _post(body: dict, cache: str, tries: int = 3) -> list[dict]:
    p = RAW / body["year"] / f"{cache}.json"
    if p.exists():
        return json.loads(p.read_text())
    for i in range(tries):
        try:
            r = requests.post(API, json=body, timeout=120, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            rows = r.json()
            if not isinstance(rows, list):
                raise IngresError(f"unexpected response for {cache}: {str(rows)[:200]}")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(rows))
            time.sleep(0.5)
            return rows
        except (requests.RequestException, ValueError) as exc:
            if i == tries - 1:
                raise IngresError(f"{cache}: {exc!r}") from exc
            time.sleep(5 * (i + 1))
    raise AssertionError("unreachable")


def real_rows(rows: list[dict]) -> list[dict]:
    """Drop the aggregate 'total' row that every response carries."""
    return [r for r in rows if (r.get("locationName") or "").strip().lower() != "total" and r.get("locationUUID")]


def states(year: str = YEAR) -> list[dict]:
    rows = real_rows(_post(_payload("INDIA", "COUNTRY", INDIA_UUID, INDIA_UUID, year, "safe"), "country"))
    if len(rows) < 30:
        raise IngresError(f"only {len(rows)} states returned for {year}")
    return rows


def districts(state: dict, year: str = YEAR) -> list[dict]:
    name = state["locationName"]
    rows = real_rows(_post(_payload(name, "STATE", state["locationUUID"], INDIA_UUID, year, "safe"),
                           f"state_{name.replace(' ', '_')}"))
    if not rows:
        raise IngresError(f"no districts for {name} {year}")
    return rows


def units(district: dict, state: dict, year: str = YEAR) -> list[dict]:
    """Blocks / mandals / taluks / firkas inside one district."""
    name = district["locationName"]
    return real_rows(_post(_payload(name, "DISTRICT", district["locationUUID"], state["locationUUID"], year),
                           f"district_{state['locationName'].replace(' ', '_')}_{name.replace(' ', '_')}"))
