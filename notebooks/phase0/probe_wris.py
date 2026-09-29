"""Phase 0 probe: CGWB groundwater levels via India-WRIS.

Recipe from neer-vazhvu's pan-India playbook (MIT). Master-list endpoints as
seen in Daksh17440/my_etl_pipeline (no license; endpoint names only).
Tests: reachability, whether a JSESSIONID cookie is needed, pagination,
and the extra fields in download=true CSV.

Usage: python notebooks/phase0/probe_wris.py [STATE] [DISTRICT]
"""

import io
import sys
from datetime import date

import pandas as pd

from _probe import run

BASE = "https://indiawris.gov.in"
GWL = f"{BASE}/Dataset/Ground%20Water%20Level"
STATE = sys.argv[1] if len(sys.argv) > 1 else "Maharashtra"
DISTRICT = sys.argv[2] if len(sys.argv) > 2 else "Pune"
PAGE = 9000
BROWSER_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": BASE,
    "Referer": f"{BASE}/dataSet/",
}


def pick(items: list[dict], keys: tuple[str, ...], want: str) -> dict | None:
    for it in items:
        for k in keys:
            if str(it.get(k, "")).strip().lower() == want.lower():
                return it
    return None


def body(p):
    p.session.headers.update(BROWSER_HEADERS)

    # 1. OpenAPI description (optional, tells us the contract if it is public)
    r = p.http("api_docs", "GET", f"{BASE}/v3/api-docs", required=False)
    if r is not None and r.ok:
        p.save_raw("wris_api_docs.json", r.content)

    # 2-4. Master lists, with no cookie, to learn if a session is required
    r = p.http("dataset_list", "POST", f"{BASE}/DataSet/DataSetList",
               json={"headers": {"normalizedNames": {}, "lazyUpdate": None}}, required=False)
    state_name, district_name = STATE, DISTRICT
    if r is not None and r.ok:
        p.save_raw("wris_dataset_list.json", r.content)
        data = r.json()
        items = data if isinstance(data, list) else data.get("data", data)
        ds = pick(items, ("datasetname", "dataSetName", "dname", "name"), "Ground Water Level") if isinstance(items, list) else None
        p.note("dataset_list_count", len(items) if isinstance(items, list) else None)
        p.note("gwl_dataset_entry", ds)
        dcode = ds and (ds.get("datasetcode") or ds.get("dcode") or ds.get("dataSetCode"))
        if dcode:
            r = p.http("state_list", "POST", f"{BASE}/masterState/StateList",
                       json={"datasetcode": dcode}, required=False)
            if r is not None and r.ok:
                states = r.json()
                states = states if isinstance(states, list) else states.get("data", [])
                p.save_raw("wris_state_list.json", r.content)
                p.note("state_count", len(states))
                st = pick(states, ("statename", "stateName", "name"), STATE)
                p.note("state_entry", st)
                scode = st and (st.get("statecode") or st.get("stateCode"))
                if scode:
                    r = p.http("district_list", "POST", f"{BASE}/masterDistrict/getDistrictbyState",
                               json={"statecode": scode, "datasetcode": dcode}, required=False)
                    if r is not None and r.ok:
                        dists = r.json()
                        dists = dists if isinstance(dists, list) else dists.get("data", [])
                        p.save_raw(f"wris_districts_{STATE}.json", r.content)
                        p.note("district_count_in_state", len(dists))
                        p.note("district_sample", dists[:3])
                        d = pick(dists, ("districtname", "districtName", "name"), DISTRICT)
                        if d:
                            district_name = d.get("districtname") or d.get("districtName") or d.get("name")
                    state_name = st.get("statename") or st.get("stateName") or st.get("name")

    # 5. Levels for one district, paginated, no cookie
    rows, page = [], 0
    params = {
        "stateName": state_name, "districtName": district_name, "agencyName": "CGWB",
        "startdate": "1990-01-01", "enddate": date.today().isoformat(),
        "download": "false", "page": 0, "size": PAGE,
    }
    while True:
        params["page"] = page
        r = p.http(f"gwl_page_{page}", "POST", GWL, params=params, timeout=180)
        j = r.json()
        batch = j if isinstance(j, list) else (j.get("data") or j.get("content") or [])
        if page == 0:
            p.save_raw(f"wris_gwl_{state_name}_{district_name}_page0.json", r.content)
            p.note("response_top_level", type(j).__name__ if isinstance(j, list) else list(j.keys()))
        rows.extend(batch)
        if len(batch) < PAGE:
            break
        page += 1
    if not rows:
        raise RuntimeError("zero rows returned: check state/district spelling")

    df = pd.DataFrame(rows)
    df.to_csv(p.save_raw(f"wris_gwl_{state_name}_{district_name}.csv", b""), index=False)
    t = pd.to_datetime(df["dataTime"], errors="coerce")
    p.note("columns", list(df.columns))
    p.note("rows", len(df))
    p.note("pages", page + 1)
    p.note("stations", int(df["stationCode"].nunique()))
    p.note("first_reading", str(t.min()))
    p.note("latest_reading", str(t.max()))
    p.note("lag_days", (pd.Timestamp.today() - t.max()).days)
    p.note("acquisition_modes", df["dataAcquisitionMode"].value_counts().to_dict())
    p.note("station_status", df["stationStatus"].value_counts().to_dict())
    p.note("units", df["unit"].value_counts().to_dict())
    v = pd.to_numeric(df["dataValue"], errors="coerce")
    med = v.groupby(df["stationCode"]).median()
    p.note("stations_by_median_sign", {"positive": int((med > 0).sum()), "negative": int((med < 0).sum()), "zero": int((med == 0).sum())})
    p.note("value_range", [float(v.min()), float(v.max())])
    p.note("outside_-5_100_envelope", int(((v < -5) | (v > 100)).sum()))
    manual = df[df["dataAcquisitionMode"].str.lower().ne("telemetric")]
    yrs = pd.to_datetime(manual["dataTime"], errors="coerce").dt.year.groupby(manual["stationCode"]).nunique()
    p.note("manual_stations_with_10plus_years", int((yrs >= 10).sum()))
    p.note("readings_by_month_manual", pd.to_datetime(manual["dataTime"], errors="coerce").dt.month.value_counts().sort_index().to_dict())

    # 6. CSV download variant: extra columns?
    csv_params = dict(params, download="true", page=0, size=100000, startdate="2023-01-01")
    r = p.http("gwl_csv_download", "POST", GWL, params=csv_params,
               headers={"Accept": "text/csv"}, required=False, timeout=180)
    if r is not None and r.ok:
        p.save_raw(f"wris_gwl_{state_name}_{district_name}_download.csv", r.content)
        try:
            c = pd.read_csv(io.BytesIO(r.content))
            p.note("csv_columns", list(c.columns))
            p.note("csv_rows_since_2023", len(c))
        except Exception as exc:
            p.note("csv_parse_error", repr(exc))
            p.note("csv_head", r.text[:300])


if __name__ == "__main__":
    run("wris", body)
