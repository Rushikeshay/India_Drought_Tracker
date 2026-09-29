# India Water Stress Tool — Project Plan

Working name: TBD. Status: planning. Last updated: 2026-09-28.

## 1. Goal

A public web tool that shows, for every district in India, whether this year's **rain** and **groundwater** are adequate, and what a **dry next year** would mean.

Audience: intermediaries (NGOs, extension officers, journalists, district officials). Not farmers directly in v1.

Core idea: drought declaration in India is gated on rainfall (Manual for Drought Management 2020). Groundwater is only an optional impact indicator. So:
- A district with normal rain but depleted groundwater cannot be declared ("hidden drought").
- A district with poor rain but good groundwater may be declared while it is actually buffered.

The tool makes both cases visible and adds a next-year outlook.

## 2. Decisions made

| Topic | Decision |
|---|---|
| Geography | National, district level. Block level later. |
| Audience | Intermediaries |
| Hosting | Public GitHub repo + GitHub Pages |
| Front end | Plain HTML/CSS/JS + D3. No build step. |
| Data refresh | Scheduled Python pipeline on GitHub Actions writes static JSON; page reads JSON on load |
| Rain axis | IMD season-to-date departure (SW monsoon Jun–Sep; NE monsoon Oct–Dec for NE-monsoon districts). Water-year total shown alongside. |
| Groundwater axis | Per-well percentile vs its own same-season history; district = median. Low = ≤ 20th percentile. Also show CGWB's rise/fall in meters vs 10-year mean. |
| Minimum data | District classified only with ≥ 5 wells that each have ≥ 10 years of same-season readings. Otherwise "insufficient data". |
| Outlook | Always show dry/normal scenarios + current ENSO odds (with "low skill before April" note). Add IMD / IRI forecasts when issued. |
| Declarations | v2, as a hand-maintained CSV |
| Language | English v1, all UI strings in a JSON file so Hindi/Marathi can be added |

## 3. How "live" updates work

1. A GitHub Actions cron job runs `pipeline/run.py` daily.
2. The script fetches new data from each source, processes it, and writes `web/data/*.json`.
3. If anything changed, the job commits the files. GitHub Pages redeploys.
4. A visitor's browser loads `index.html`, which fetches the JSON and draws the map.

Why not fetch sources directly in the browser: government portals usually block cross-origin requests (CORS), are slow, and go down. The sources update daily to yearly, so a daily pipeline is as current as the data allows. Every layer shows an "as of" date.

## 4. Data layers

### 4.1 Rainfall (current season)

| Option | Level | Update | Notes |
|---|---|---|---|
| **IMD gridded 0.25° daily rainfall** via `imdlib` (`get_data` for history since 1901, `get_real_data` for recent) | Grid → district by spatial overlay | Daily | **Chosen.** Authoritative, long history, needed for normals and scenarios too. |
| IMD district-wise departure pages (mausam.imd.gov.in) | District | Daily | Use to **validate** our numbers. |
| CHIRPS 0.05° | Grid | Pentad | Fallback if IMD real-time fails. |

Metrics:
- Season-to-date rainfall departure (%) vs normal.
- IMD categories: Large excess (≥ +60), Excess (+20 to +59), Normal (−19 to +19), Deficient (−20 to −59), Large deficient (≤ −60).
- SPI-3 and SPI-6 (computed from the same data), shown as supporting info.
- NE-monsoon districts: Tamil Nadu, Puducherry, coastal AP, Rayalaseema, south interior Karnataka, Kerala. Their rain axis switches to the Oct–Dec season on Oct 1.

Phase 2 check: which normal period IMD currently uses for district normals. Match it.

### 4.2 Groundwater level (current state)

**Source: CGWB wells via India-WRIS API.** ~25,000 wells nationally. Readings 4×/year (Jan, pre-monsoon Mar–May, Aug, Nov); newer telemetric wells every 6 hours.

Endpoint recipe (from neer-vazhvu's pan-India playbook, proven July 2026; not yet tested by us):
- `POST https://indiawris.gov.in/Dataset/Ground%20Water%20Level?stateName=..&districtName=..&agencyName=CGWB&startdate=YYYY-MM-DD&enddate=YYYY-MM-DD&download=false&page=0&size=9000`
- Params go in the **query string**, not a JSON body.
- All params required. Blank `districtName` returns **zero rows, not all rows**. Iterate every district explicitly.
- Paginate until a short page.
- Reported reachable from non-India IPs (this endpoint only; `arc.indiawris.gov.in` is blocked).
- Returns `stationCode`, `stationName`, `latitude`, `longitude`, `district`, `tehsil`, `dataAcquisitionMode`, `stationStatus`, `dataValue`, `dataTime`, `unit`.

District list for iteration: WRIS master endpoints seen in Daksh17440's extractor:
- `POST /DataSet/DataSetList`
- `POST /masterState/StateList` with `{"datasetcode": ..}`
- `POST /masterDistrict/getDistrictbyState` with `{"statecode": .., "datasetcode": ..}`

That extractor also uses a copied browser `JSESSIONID` cookie and `download=true` (CSV with extra fields: `well_type`, `well_depth`, `well_aquifer_type`, `block`). Test in Phase 0 whether the cookie is needed and whether the CSV fields are worth using. It has no license, so use it as reference only.

Known traps (from the playbook):
- **Sign convention differs by station family** (positive-down vs negative-down). Derive per station from its own median. Never `abs()`.
- **Sanity envelope**: drop readings outside about −5 to 100 m below ground and log what was dropped.
- **Liveness**: some districts have stale data (e.g. Gurugram, nothing since 2020). Track last reading date per district.
- **Telemetric vs manual**: reduce 6-hourly telemetry to the four standard cycles before computing percentiles.

Metrics:
- Per well: depth for each cycle; percentile vs that well's own history for the same cycle (≥ 10 years).
- Per district: median well percentile → Low if ≤ 20th. Also median rise/fall (m) vs 10-year mean for the same cycle.
- Assign wells to districts by **lat/lon spatial join** to our boundaries, not by WRIS district name.

Fallbacks: CGWB Ground Water Year Books (PDF); data.gov.in groundwater datasets.

### 4.3 Groundwater stress (structural)

**Source: IN-GRES** (CGWB + IIT Hyderabad), Dynamic Ground Water Resources Assessment. Annual since 2022; 2025 edition is latest.

- API: `POST https://ingres.iith.ac.in/api/gec/getBusinessDataForUserOpen`, JSON body, no auth. Hosted outside NICNET, reachable from any IP.
- Working payloads in neer-vazhvu's `build_ingres_gwr.py` (MIT license, reusable with attribution). Key gotchas:
  - Lowercase keys (`locname`, `loctype`, `locuuid`); `locname` with no spaces ("WESTBENGAL").
  - `parentuuid` is required. Wrong value returns HTTP 200 with an empty table.
  - A COUNTRY-level call (`locuuid = parentuuid = ffce954d-24e1-494b-ba7e-0931d8ad6085`) returns all states with UUIDs. Get UUIDs this way, not from the site's JS bundle.
  - Children of a district: `loctype=DISTRICT`, `locuuid=<district>`, `parentuuid=<state>`.
- Manual fallback: the portal's table view (misview) has a download button.
- Categories: Safe / Semi-critical / Critical / Over-exploited, plus **Saline** units with no extraction figures. Show saline as its own category.
- Assessment units changed over time in some states. Don't stitch trends across a unit change.
- Show district stage of extraction, and flag districts where any block is Critical/Over-exploited (district totals can hide them — e.g. Pune district Safe while Shirur block is Critical).

### 4.4 Drought indices (cross-check)

**IIT Gandhinagar India Drought Monitor** (github.com/wcl-iitgn/IndianDroughtMonitor). Weekly SPI, soil moisture (SSMI), runoff (SRI), composite index, 7/15/30-day forecasts. Text grids on GitHub; district stats file exists. **No license file found — ask the lab before reusing.** Use for cross-checks and an optional soil-moisture layer.

### 4.5 Outlook (next season)

No source forecasts district rainfall a year ahead with useful accuracy. The plan uses **scenarios**, anchored by whatever real forecast exists at that time of year.

| Source | Horizon | Level | Use |
|---|---|---|---|
| **CPC/IRI ENSO probabilities** | ~9 months | Global index | Monthly. Odds of El Niño / La Niña. Weak skill before April. |
| **IRI NMME India precipitation probability** (iridl.ldeo.columbia.edu) | 1–6 months | Grid → district | Tercile odds. |
| **IMD Long Range Forecast** | Next monsoon | National / broad regions | April and late May/June. Enter by hand. |

Scenario engine (per district):
1. From IMD 1901–present, get the distribution of seasonal rainfall. Dry year = 20th percentile; normal = median.
2. From years with well data, fit the relationship between seasonal rain departure and groundwater change (pre- to post-monsoon).
3. Project next post-monsoon groundwater percentile under each scenario, with an uncertainty band.
4. Show how often dry years occurred in El Niño years vs all years, next to current ENSO odds.
5. Label "scenario, not forecast." Hide where the fit is weak or data is thin.

### 4.6 Boundaries

| Option | Notes |
|---|---|
| **LGD / Survey of India districts via india-geodata** (yashveeeeeeer.github.io/india-geodata, CC0) | First choice. Check vintage and LGD codes. |
| udit-001/india-maps-data (MIT, ~759 districts) | Backup. |
| DataMeet (Census 2011) | Crosswalks only. |

Every table keys on **LGD district code**. `district_crosswalk.csv` maps source names (IN-GRES, IMD pages) to codes. Simplify geometry with mapshaper to TopoJSON < 2 MB. Use a Survey of India–conformant national outline.

### 4.7 Later layers (v2+)

- Official drought declarations (hand CSV: state, district, tehsil, season, date, order link).
- Reservoir storage (CWC weekly bulletin, ~150 reservoirs).
- Vegetation (NDVI/VCI).
- Block-level view (IN-GRES already has blocks).

## 5. Classification

Per district, current season:

| | Groundwater OK | Groundwater low |
|---|---|---|
| **Rain OK** | Fine | Hidden drought |
| **Rain short** | Buffered | Double drought |

- Rain short = IMD category Deficient or worse, season-to-date.
- Groundwater low = district median well percentile ≤ 20th for the latest cycle.
- Insufficient data = fewer than 5 qualifying wells, or latest reading older than one cycle.
- Secondary marks: IN-GRES category; well count and data age.

## 6. Architecture

```
repo/
  pipeline/
    sources/        # one module per source: fetch() -> raw files
    process/        # clean, aggregate to district, compute metrics
    outlook/        # scenario engine, ENSO, NMME
    run.py          # entry point: fetch -> process -> export
  data/
    raw/            # cached downloads (gitignored, except small files)
    processed/      # parquet; DuckDB for queries
    reference/      # boundaries, crosswalk, normals
  web/
    index.html  district.html  methods.html
    js/ css/ i18n/en.json
    data/           # exported JSON the site reads (committed)
  notebooks/        # phase 0 exploration
  docs/sources.md   # every source: URL, license, access method, quirks
  .github/workflows/refresh.yml
```

Tools: Python 3.11, pandas, geopandas, xarray, `imdlib`, `exactextract` or `rasterstats`, DuckDB, requests. Front end: D3 v7, topojson-client.

Refresh: rainfall daily; ENSO/NMME monthly; groundwater checked daily (changes ~4×/year; full national pull is slow, so fetch incrementally and cache); IN-GRES yearly.

## 7. Front end (v1)

1. **National map.** Quadrant colors (2×2 legend), hatching for insufficient data. Toggle single layers: rain departure, groundwater percentile, stage of extraction, outlook.
2. **District panel.** Rain departure this season; groundwater time series with 10-year band; stage of extraction and worst block; scenario outcome; well count; "as of" dates; source links.
3. **Hidden-drought table.** Sortable list of districts by quadrant, with CSV download.
4. **Methods page.** Definitions, thresholds, sources, limits.
5. Mobile-friendly, English, strings from `i18n/en.json`.

## 8. Phases

Each phase ends with a short review before moving on.

| # | Phase | Output | Done when |
|---|---|---|---|
| 0 | Access tests | Notebook per source; `docs/sources.md` | Pulled one district each from WRIS, IMD gridded, IN-GRES, IDM, ENSO from **both** my laptop and a GitHub Actions runner; formats, lags, and reachability recorded |
| 1 | Boundaries + district master | `districts.topojson`, `district_master.csv` (LGD codes) | All districts render; codes unique |
| 2 | Rainfall pipeline | Season-to-date departure + SPI per district | Matches IMD district departure pages for a sample within a few % |
| 3 | Groundwater pipeline | Well → district percentiles and meters vs 10-yr mean | Signs, envelope, staleness handled; sane results for known cases (Punjab, Marathwada, Delhi) |
| 4 | Stress layer | IN-GRES 2025 joined to districts, incl. worst block | All districts matched or listed as unmatched |
| 5 | Classification + validation | Quadrant per district; unit tests | Back-test on past years (e.g. 2023) vs known droughts |
| 6 | Front end v1 | Map, panel, table, methods | Works on phone and laptop |
| 7 | Automation | `refresh.yml` | Runs daily unattended for 2 weeks |
| 8 | Outlook | Scenario engine + ENSO/NMME layer | Back-test: did scenarios bracket actual outcomes? |
| 9 | Launch + feedback | Public site | 3–5 intermediaries try it; notes logged |

## 9. Risks

- **Undocumented APIs** (WRIS, IN-GRES) can change without notice. Cache raw pulls; fail loudly; keep the manual download path documented.
- **IP blocking.** Reported open from any IP, but probe from GitHub Actions in Phase 0. Fallback: run that step locally and commit results.
- **Groundwater is local.** District medians hide variation between aquifers and wells. Say so on the page.
- **Sparse or stale wells** in some districts. Minimum-data rule + "as of" dates.
- **District boundaries change.** Key on LGD codes; keep a crosswalk.
- **Official map rules.** Use a Survey of India–conformant national outline.
- **Licenses.** Confirm IIT-GN data terms. Credit neer-vazhvu (MIT) for reused code.

## 10. Open questions

1. Name and domain for the site?
2. IIT-GN data: will the lab allow reuse? (Email before Phase 8.)

## 11. Reference code

- neer-vazhvu (MIT): `docs/methodology/pan-india-source-playbook.md`, `neer-vazhvu-api/scripts/build_ingres_gwr.py`, `build_delhi_cgwb_stations.py` — github.com/SundareshPrasanna/neer-vazhvu
- Daksh17440/my_etl_pipeline `wris_extractor/` (no license; reference only)
- DrJagadeeshG/india-water-data — WRIS client covering all dataset endpoints

## 12. Instructions for Claude Code

- Work one phase at a time. Stop at the end of each phase and summarize for review.
- Never invent or hard-code data values. If a source fails, log it and stop.
- Record every source URL, access date, and license in `docs/sources.md`.
- Keep raw downloads out of git unless small.
- Write tests for classification and aggregation logic.
- Ask before adding a dependency not listed in section 6.
