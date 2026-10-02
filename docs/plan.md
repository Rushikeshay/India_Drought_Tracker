# India Drought & Groundwater Watch — Plan (v2)

Tagline / web address: **Hidden Drought** (e.g. hiddendrought.in, domain not yet bought).

Repo: github.com/Rushikeshay/India_Drought_Tracker · Updated 2026-10-01 · v1 of this plan is in git history (commit 4a489fe).
Source details, URLs, quirks and test results: [sources.md](sources.md). This file holds the decisions and the status.

## 1. Goal

A public website that shows, for every Indian district, whether **rain** and **groundwater** are adequate, how a **drought index** (IIT-GN IDM) rates it, and what a dry next year would mean. Official declarations are deferred to v2. Audience: intermediaries (NGOs, extension officers, journalists, district officials).

Core idea: drought declaration is gated on rainfall (Drought Manual 2020), so:
- **Hidden drought:** normal rain but depleted groundwater, so no declaration.
- **Buffered:** poor rain but good groundwater.

## 2. Two tiers

| Tier | Period | Layers | What it answers |
|---|---|---|---|
| **Historical** | ~2000–2023 | Rain, groundwater trend, IN-GRES stress (IDM index from Jul 2021) | Long-term pattern for the district. Context where current data is thin. |
| **Current** | 2024–now | Rain season-to-date, latest groundwater level, IDM drought index, ENSO outlook | How the district is doing right now. |

## 3. Coverage without an India IP (measured 2026-10-01, 785 LGD districts)

| Layer | Historical 2000–2023 | Current 2024–now |
|---|---|---|
| Rain (IMD gridded) | 100% | 100% (daily) |
| GW: ≥ 1 well | 91% | 57% live in the last 60 days · 76% with any 2024+ reading |
| GW: ≥ 3 wells, ≥ 5 yrs history | 85% | 2% (telemetry only) to 23% (if paired with old manual wells) |
| GW: ≥ 5 wells, ≥ 10 yrs (v1 rule) | 78% | ≤ 9% |
| IDM drought index | Weekly grids from Jul 2021 only | District stats weekly (740 districts by name) |
| Declarations | Deferred to v2 | Deferred to v2 |

Reproduce with `notebooks/phase0/coverage.py`.

## 4. Data sources (decided)

| Layer | Source | Access | Refresh |
|---|---|---|---|
| Rain | IMD 0.25° gridded: yearly files (**1971**–last year; 1951–1970 kept from the first build) + real-time daily. Daily grids are reduced to districts and deleted; we store district **monthly** history, district daily **normals**, and **current-season daily** only | POST to imdpune.gov.in; works from any IP | Daily; re-fetch the last 7 days (newest file may be preliminary) |
| GW history | **NWDP** CGWB manual quarterly CSVs, 1991–2025 (most states end 2023–24) | nwdp.nwic.gov.in CKAN; any IP; includes LGD codes | One-time + yearly |
| GW current | **NWDP** CGWB telemetry six-hourly, 2026–2030 files (~3,500 live wells) | Same; 2-day lag | Daily |
| GW stress | IN-GRES, **2025-2026** edition, district + block | Open JSON API | Yearly |
| Detected drought | IIT-GN India Drought Monitor: CDI grids (weekly since 2021-07-14), district stats (current week), SPI/SRI/SSMI | GitHub raw files + data-query tool | Weekly. Used with attribution to IIT-GN Water and Climate Lab (owner's decision 2026-10-01) |
| ENSO | NOAA CPC strength-probability table (RONI-based) | HTML table | Monthly (2nd Thursday) |
| NMME rain terciles | IRI Data Library | Reachable | Monthly (Phase 9) |
| Boundaries | india-geodata `LGD_Districts` (785 districts, Dec 2023, CC0) | GitHub release | Fixed |

**Dropped from the default path:** India-WRIS. It's blocked outside India (NICNET), and fresh manual readings 2024+ exist only there. An optional upgrade is ready but untested: a free Oracle VM in India (`deploy/oracle/`, `pipeline/sources/wris.py`). It would raise current-tier GW coverage to about 57% at full rigour (450 districts have long-history manual wells). Revisit after launch.

## 5. Groundwater method (revised)

- Assign wells to districts by **lat/lon spatial join**, never by the source's district name. Station names change between files ("X" vs "X_1"), so key wells on coordinates.
- **Sign:** manual readings are positive-down; telemetry is negative-down (92%). Derive per well from its own median. Never `abs()`. Drop values outside −5 to 100 m and log them.
- Telemetry: reduce six-hourly readings to the 4 standard cycles (Jan, pre-monsoon Mar–May, Aug, Nov).
- **Well pairing:** link a telemetry well to the manual well at the same site (≤ 50 m) only if their readings agree where they overlap (2021–2023). Some sites have a deep sensor next to a shallow well (Andheri Devi: 33.9 m vs 7.5 m).
- **District confidence tiers** (shown on the site):
  - **Full:** ≥ 5 wells with ≥ 10 same-season years.
  - **Short record:** ≥ 3 wells with ≥ 5 years.
  - **Level only:** ≥ 1 live well. Show the latest level and the change this season, with no percentile.
  - **Insufficient:** none of the above.
- Low groundwater = district median well percentile ≤ 20th. Also show the change in metres vs the multi-year mean.

## 6. Drought declarations: deferred to v2 (decided 2026-10-01)

Out of v1. No national machine-readable dataset exists; states publish their own notifications. The IDM index is a **detected** drought measure and is always labelled that way, never as "declared".
v2 options: a hand-compiled CSV `data/reference/declarations.csv` (state, district, tehsil, season, year, date, order URL) from state notifications, starting with drought-prone states. Then show declared vs detected side by side.

## 7. Classification (current tier)

| | GW OK | GW low |
|---|---|---|
| **Rain OK** | Fine | Hidden drought |
| **Rain short** (IMD Deficient or worse, season-to-date) | Buffered | Double drought |

Secondary marks: GW confidence tier, IN-GRES category and worst block, IDM drought class, data age. NE-monsoon districts (Tamil Nadu, Puducherry, coastal AP, Rayalaseema, south interior Karnataka, Kerala) switch to the Oct–Dec season on Oct 1.

## 8. Phases and status

| # | Phase | Status | Done when |
|---|---|---|---|
| 0 | Access tests | ✅ **Done** (WRIS blocked → NWDP) | Probes from laptop + Actions; sources.md; coverage measured |
| 1 | Boundaries + district master | ✅ **Done 2026-10-01** (awaiting review) | 783 districts + 2 PoK outline polygons; `web/data/districts.geojson` 1.9 MB (simplified GeoJSON; no TopoJSON needed); IN-GRES crosswalk 723/733 rows; 11 tests pass |
| 2 | Rainfall pipeline | ⏭ **Next** | Season-to-date departure + SPI per district; matches IMD district pages within a few % |
| 3 | Groundwater pipeline (NWDP) | — | History + telemetry merged; signs, envelope, pairing, tiers; sane for Punjab, Marathwada, Delhi |
| 4 | Stress layer (IN-GRES) | — | 2025-26 edition joined incl. worst block; unmatched listed |
| 5 | IDM drought layer | — | Weekly CDI grids → district stats with our own boundaries (back to Jul 2021); crosswalk of IDM names → LGD |
| 6 | Classification + validation | — | Both tiers; unit tests; back-test 2023 vs known droughts |
| 7 | Front end v1 | — | Map, district panel, hidden-drought table, methods page; phone + laptop |
| 8 | Automation | — | `refresh.yml` daily on Actions, unattended for 2 weeks |
| 9 | Outlook | — | Scenario engine + ENSO/NMME; back-test |
| 10 | Launch + feedback | — | 3–5 intermediaries try it |

## 9. Architecture (unchanged)

`pipeline/` (sources → process → outlook → `run.py`) → `web/data/*.json` (committed) → GitHub Pages (plain HTML/JS + D3, no build). Raw downloads go in `data/raw/` (gitignored). Python 3.11 in `.venv` via uv; dependencies are in `requirements.txt` only (pandas, geopandas, xarray, imdlib, duckdb, requests). Ask before adding any others. `pyarrow` approved 2026-10-01 (parquet). Tests use stdlib `unittest`: `.venv/bin/python -m unittest discover -s tests -t .`

## 10. Open items

Phase 1 follow-ups: (a) **Decided 2026-10-01:** keep Rajasthan's 50-district map (9 districts abolished Dec 2024 stay, flagged) and show each source at the level it reports. Never re-apportion data to new boundaries; (b) districts newer than the Dec 2023 map (MP: Pandhurna, Maihar, Mauganj; AP: Markapuram, Polavaram; Gujarat: Vav-Tharad) aren't on it; (c) 64 map districts have no IN-GRES row (carved-out districts and Uttarakhand hills). Phase 4 falls back to the parent or marks them "not assessed". Delhi's IN-GRES units don't match LGD.


1. Buy the domain (hiddendrought.in or similar).
2. Licenses still to confirm: IMD gridded data terms; India Data Portal dataset (`isopen: false`).
3. Later: Oracle/WRIS upgrade for current-tier groundwater; declarations (v2).

## 11. Working rules (for Claude Code)

One phase at a time; stop and summarize at the end of each. Never invent data; if a source fails, log it and stop. Record every source in sources.md. Write tests for aggregation and classification. Commit as Rushikeshay / rushikesh.y.jadhav@gmail.com.
