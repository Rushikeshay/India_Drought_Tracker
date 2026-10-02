# Data sources

Every source used by the pipeline: URL, license, access method, quirks, and the
Phase 0 access test results. Probe scripts: `notebooks/phase0/probe_*.py`.
Machine-readable results: `notebooks/phase0/results/<laptop|gha>/<source>.json`.

Phase 0 laptop run: 2026-09-29 02:16–02:25 UTC, egress **US** (Comcast, AS7922).
The maintainer works outside India, so "laptop" is also a non-India IP.
GitHub Actions run: 2026-09-29 ~02:40 UTC, egress US (Microsoft AS8075). Results match the laptop run exactly.

## Access summary

| Source | Layer | Laptop (US) | GH Actions | Lag / freshness |
|---|---|---|---|---|
| IMD gridded rain (imdpune.gov.in) | Rainfall | ✅ | ✅ | Real-time: day D is available on D (IST). Historical: 2025 is the latest full year |
| IN-GRES (ingres.iith.ac.in) | GW stress | ✅ | ✅ | Edition 2025-2026 served |
| India-WRIS GW levels (indiawris.gov.in) | GW level | ❌ TCP connect timeout | ❌ TCP connect timeout | — |
| NWDP CGWB quarterly GW levels (nwdp.nwic.gov.in) | GW history | ✅ | ✅ | **2–4 years behind**: most states end 2023–Jan 2024 |
| IIT-GN India Drought Monitor (GitHub) | Cross-check | ✅ | ✅ | Weekly; latest week ending 2026-09-23, committed 2026-09-24 |
| NOAA CPC ENSO probabilities | Outlook | ✅ | ✅ | Monthly (2nd Thursday). Issued Sep 2026; next 8 Oct 2026 |
| IRI ENSO plume SVG / IRI Data Library | Outlook | ✅ reachable | ✅ reachable | Monthly |
| mausam.imd.gov.in (validation pages) | Rainfall check | ✅ reachable | ✅ reachable | — |

---

## 1. IMD gridded daily rainfall, 0.25°

- **Historical (yearly files):** `POST https://imdpune.gov.in/cmpg/Griddata/rainfall.php`, form field `rain=<YYYY>`. Returns a raw `.grd` file of float32 values, 365|366 × 129 lat × 135 lon (25.4 MB/year). Grid: lat 6.5–38.5, lon 66.5–100.0. Missing value −999.
- **Real-time (daily files):** `POST https://imdpune.gov.in/cmpg/Realtimedata/Rainfall/rain.php`, form field `rain=<DDMMYYYY>`. 69,660 bytes/day (129 × 135 float32). 4,964 valid land cells.
- These are the endpoints `imdlib` 0.1.22 uses. We download them ourselves because imdlib's `requests.post` calls have **no timeout** and would hang on a blocked host. We parse with `imdlib.open_data` / `open_real_data`.
- Access: works from a US IP. Note that a plain `GET https://www.imdpune.gov.in/` timed out while the POST endpoints worked, so probe the actual endpoint.
- Tested 2026-09-28 (local): historical 2025 in 57 s; real-time files 2026-09-19 … 2026-09-28 in 2–4 s each. All files were distinct, with real rain values.
- **Quirk (to confirm in Phase 2):** the newest day had far fewer wet cells (891 vs ~1,700–2,900 on earlier days). It may be a preliminary file that gets revised. **The pipeline should re-download the last ~7 days on every run.** IMD's rain day D is the 24 h ending 08:30 IST on D, so compute "today" in IST, not local time.
- License: IMD data; terms to be checked (IMD Pune data-supply policy). **TODO Phase 2:** confirm the license and which normal period IMD's district normals use.
- Validation site `https://mausam.imd.gov.in/` is reachable (HTTP 200). The district departure page URL is still to be pinned down in Phase 2.

## 2. IN-GRES — Dynamic Ground Water Resources assessment

- `POST https://ingres.iith.ac.in/api/gec/getBusinessDataForUserOpen`, JSON body, no auth.
- Payload shape adapted from neer-vazhvu `build_ingres_gwr.py` (MIT). Keys are lowercase, and `locname` has no spaces. `parentuuid` is the discriminator:
  - Country → states: `loctype=COUNTRY`, `locuuid=parentuuid=ffce954d-24e1-494b-ba7e-0931d8ad6085`, `category="safe"`.
  - State → districts: `loctype=STATE`, `locuuid=<state>`, `parentuuid=<INDIA>`.
  - District → blocks/units: `loctype=DISTRICT`, `locuuid=<district>`, `parentuuid=<state>`, `category=null`.
- **Edition:** `year="2025-2026"` returns data. This is newer than the "2025" edition assumed in the plan. Earlier editions: 2024-2025, 2023-2024, 2022-2023, 2021-2022 (per neer-vazhvu).
- Country call returned 36 states with `locationUUID`s (raw copy: `data/raw/phase0/laptop/ingres_country_2025-2026.json`).
- Maharashtra: 37 rows = 36 districts + a `total` row (`category=None`). **Filter the `total` row.**
- Numeric fields are usually `{total, command, non_command, poor_quality}` dicts; `category` is the same shape. Pune district has `category.total = safe` but `category.poor_quality = over_exploited`. **Decide in Phase 4 which of these we show.**
- Check case: Pune district 63.7% Safe; Shirur block 95.7% **Critical**. This matches the plan's example.
- Latency: country call 5 s, state/district calls < 0.5 s.
- License: government data served openly. Payload code credit: neer-vazhvu (MIT).

## 3. India-WRIS — CGWB groundwater levels ❌ BLOCKED from US IP

- Endpoint (from the neer-vazhvu playbook): `POST https://indiawris.gov.in/Dataset/Ground%20Water%20Level?stateName=..&districtName=..&agencyName=CGWB&startdate=..&enddate=..&download=false&page=0&size=9000`.
- **Result 2026-09-29:** `indiawris.gov.in` resolves to **164.100.85.36 (NICNET)**. TCP connects to ports 443 and 80 time out, so the host is unreachable, not refusing requests. Same result for `/v3/api-docs`, `/DataSet/DataSetList` and the GWL endpoint.
- This contradicts the playbook ("works from a non-India IP", July 2026). The playbook's own rule is that NICNET 164.100.x.x hosts refuse non-India IPs, so this looks like a geo-filter that may have been added or tightened since then. The GitHub Actions runner (US, Microsoft) got the same timeout. **Chosen route: an Oracle Cloud Always Free VM in an Indian region (`deploy/oracle/`).**
- Could not test: whether a `JSESSIONID` cookie is needed, and the extra CSV fields.
- Candidate fallbacks (not yet evaluated):
  - `api.data.gov.in` is reachable from the US (it is also NICNET, 164.100.61.198). It needs a free API key; we still need to find which CGWB groundwater-level resources exist and how fresh they are.
  - `cgwb.gov.in` is reachable (HTTP 200): Ground Water Year Books (PDF, annual).
  - Run the WRIS fetch from an India IP (see open question in the Phase 0 summary).
- Reference code: DrJagadeeshG/india-water-data is **AGPL-3.0**. Read it for API knowledge only; don't copy code. Daksh17440/my_etl_pipeline has no license; endpoint names only.

## 3b. National Water Data Portal (NWDP) — CGWB groundwater levels, bulk CSV ✅ reachable, ⚠️ stale

- CKAN catalogue at `https://nwdp.nwic.gov.in/` (IP 115.112.186.119, **not NICNET**). Reachable from the US; API at `/api/3/action/package_search|package_show`.
- Dataset `gwl-manual-quarterly-central-ground-water-board-department`, "Ground Water Level (Manual - Quarterly), CGWB". License: **Other (Open)**. One CSV per state for each of 1991–2020, 2021–2025 and 2026–2030.
- Columns: `Station, Agency, State LGD Code, State, District LGD Code, District, Tehsil, Block, Village, …, Latitude, Longitude, RL_MSL, Data Acquisition Time (DD-MM-YYYY HH:MM), Groundwater Level Quarterly Manual (meter)`. **Includes LGD district codes.**
- Station names are **not stable across files** (for example "Aad (Bk)_1" in 1991–2020 vs "Aad (Bk)" in 2021–2025). Identify wells by lat/lon.
- **Freshness checked 2026-09-29:** the 2026–2030 files have 0 rows (regenerated daily, still empty). The latest reading in the 2021–2025 files by state ranges from 2022-01 (Dadra & Nagar Haveli) to 2025-01 (Tamil Nadu, Odisha). Most states end between 2023-08 and 2024-01. Maharashtra ends 2023-08-10. **2–4 years behind WRIS.**
- Use: the **historical baseline** (1991–~2023) for per-well percentiles, without an India IP. Not usable for the current season.
- **Telemetry (six-hourly DWLR), checked 2026-10-01:** datasets `ground-water-level-telemetry-daily-cgwb-as-assam` (all states, despite the name) and `ground-water-level-telemetry-hourly-…-cgwb` (Assam, Bihar). The **2026–2030 files are current**: latest reading 2026-09-29 (2-day lag), regenerated daily, ~390 MB in total. 4,565 stations; **3,466 reported in Sep 2026**, in 404 districts (≥ 5 live wells: 206 districts). Thin or dead in places: Maharashtra 29 of 174 live, Kerala none since 2026-06-19, Karnataka 127 of 386.
  - Values are **negative-down** (92% of stations have a negative January median); the manual network is positive-down. Flip per station.
  - Telemetry history starts in 2021 (2021–2025 files, ~1.6 GB), so there are **not 10 years per well**.
  - Of the live telemetry wells, 2,405 have a manual well within 200 m (names usually match, with a `_1` suffix), but only **775** of those manual wells have ≥ 10 years of January readings. That gives **65 districts with ≥ 5 such wells**. Co-located doesn't always mean the same well: some telemetry sensors sit in deeper piezometers (Andheri Devi: −33.9 m telemetry vs 7.5 m manual). Same-well identity needs checking against the 2021–2023 overlap.
  - For comparison, the **manual network** has 10,711 wells with ≥ 10 years of January history still measured in 2023+, covering **450 districts with ≥ 5 wells**. Its 2024–2026 readings are only on WRIS.
- Also found (not probed in depth): the India Data Portal (ISB) CKAN at `ckandev.indiadataportal.com`, dataset `cgwb-changes-in-depth-to-water-level`. Reachable; `isopen: false`.

## 4. IIT Gandhinagar — India Drought Monitor (cross-check only)

- Repo: `https://github.com/wcl-iitgn/IndianDroughtMonitor` (~850 MB). **No license** (GitHub API `license: null`). Do not republish until the lab agrees. **Email needed.**
- Files (raw.githubusercontent.com, `main` branch):
  - `data/Current_CDI.txt`: whitespace text `lat lon value`, 0.25° grid, 4,537 cells. Composite drought index; range this week −2.77 … 2.14.
  - `data/{SPI,SRI,SSMI}_{1,2,3,4,6,9,12,24}month.txt`, `*_{7,15,30}day_anomaly.txt`, and forecasts `Future_CDI_{7,15,30}day.txt`, `{P,R,SM}_mag_*day.txt`.
  - `data/districts/district-stats.json`: `{week_ending, districts:[{district, state, state_id, none_pct, d0_pct … d4_pct, drought_pct}]}`, **740 districts, keyed by name only (no LGD code)**. We'd need a crosswalk.
  - `data/summary_latest.txt`: national summary prose, with the week-ending date.
- Update: weekly. Latest week ending 2026-09-23; `Current_CDI.txt` committed 2026-09-24 (4 days old at probe time).

## 5. ENSO outlook — NOAA CPC

- **Official probabilities:** `https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/strengths/`. Static HTML table `#probabilities-table`: 9 overlapping 3-month seasons × 9 RONI strength bins (≤ −2.0 … ≥ +2.0 °C). The probe sums them into La Niña / Neutral / El Niño and checks the column headers first.
  - Quirks: the headers use a Unicode minus (U+2212), and the page keeps an old `Issued <month>` heading inside an HTML comment. Strip comments before parsing.
  - CPC now verifies against **RONI** (Relative Oceanic Niño Index), not ONI. The historical El Niño year list used for the scenario engine (Phase 8) needs to follow the same index. **TODO Phase 8.**
- Discussion page: `https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml` gives the next issue date ("8 October 2026").
- Update: 2nd Thursday of each month.
- License: US Government work, public domain.
- IRI: `https://ensoforecast.iri.columbia.edu/figure3_plot/<Y>/<M>` serves the model-based probability plot as an **SVG only** (no data table found). Not used for numbers.
- IRI Data Library `https://iridl.ldeo.columbia.edu/` is reachable. It is the source for NMME precipitation terciles (Phase 8).

## 6. Boundaries

- india-geodata release `admin/districts`, `LGD_Districts.geojsonl.7z` (CC0): https://github.com/yashveeeeeeer/india-geodata/releases/tag/admin/districts. Downloaded 2026-10-01; file dated 2023-12-11.
- 785 polygons, EPSG:4326, LGD codes in `dist_lgd`. Two are PoK (Mirpur, Muzaffarabad) with `dist_lgd = 0`: kept in the outline, not in the master table. 10 invalid geometries repaired with `make_valid`. The national outline includes all of J&K and Ladakh (official map).
- Vintage gaps: Rajasthan's 9 districts abolished in Dec 2024 are still present (flagged). MP's Pandhurna, Maihar and Mauganj, AP's Markapuram and Polavaram, and Gujarat's Vav-Tharad are absent.
- All 643 district LGD codes in NWDP groundwater data exist on this map (except Kolkata, coded 9999 in NWDP; wells are joined spatially anyway).
- LGD directory (lgdirectory.gov.in, NICNET) is reachable from the US, but bulk download needs a CAPTCHA, and the guessed web-service URLs return 404.
- Build: `python -m pipeline.process.boundaries`. Crosswalk: `python -m pipeline.process.crosswalk`.

## Reference code and credits

- neer-vazhvu, MIT: github.com/SundareshPrasanna/neer-vazhvu. IN-GRES payloads, WRIS playbook.
- imdlib (Nandi, Patel, Swain), MIT: file formats and endpoints.
- DrJagadeeshG/india-water-data, AGPL-3.0: reference only.
- Daksh17440/my_etl_pipeline, no license: reference only.
