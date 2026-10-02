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
| 2 | Rainfall pipeline | ✅ **Done 2026-10-01**: headline = IMD official district figure (711), gridded fallback (72); history/SPI gridded | Season-to-date departure + SPI per district; matches IMD district pages within a few % |
| 3 | Groundwater pipeline (NWDP) | ✅ **Done 2026-10-01** (awaiting review). See §10 for results | History + telemetry merged; signs, envelope, pairing, tiers; sane for Punjab, Marathwada, Delhi |
| 4 | Stress layer (IN-GRES) | ✅ **Done 2026-10-01** (awaiting review). See §10 | 2025-26 edition joined incl. worst block; unmatched listed |
| 5 | IDM drought layer | ✅ **Done 2026-10-01** (awaiting review): 775 districts weekly since 2021-07-14 | Weekly CDI grids → district stats with our own boundaries (back to Jul 2021); crosswalk of IDM names → LGD |
| 6 | Classification + validation | ✅ **Done 2026-10-01** (awaiting review). See §10 | Both tiers; unit tests; back-test 2023 vs known droughts |
| 6a | Status history (snapshots) | ✅ **Done 2026-10-01**: Jan/May/Aug/Nov from 2000, 107 snapshots, median 577 districts classified per snapshot |
| 6b | **Row-level trace (backend accuracy check)** | ⏭ **Next**: follow real rows from each raw file through every transform to status, recomputing each step independently; runs as a test |
| 7 | Front end v1 | — | Map, district panel, hidden-drought table, methods page; phone + laptop |
| 8 | Automation | — | `refresh.yml` daily on Actions, unattended for 2 weeks |
| 9 | Outlook | — | Scenario engine + ENSO/NMME; back-test |
| 10 | Launch + feedback | — | 3–5 intermediaries try it |

## 9. Architecture (unchanged)

`pipeline/` (sources → process → outlook → `run.py`) → `web/data/*.json` (committed) → GitHub Pages (plain HTML/JS + D3, no build). Raw downloads go in `data/raw/` (gitignored). Python 3.11 in `.venv` via uv; dependencies are in `requirements.txt` only (pandas, geopandas, xarray, imdlib, duckdb, requests). Ask before adding any others. `pyarrow` approved 2026-10-01 (parquet). Tests use stdlib `unittest`: `.venv/bin/python -m unittest discover -s tests -t .`

## 10. Open items

**Phase 6 results (2026-10-01):**
- **Current (rain = SW 2026 / NE season, GW = Aug 2026):** only **16 districts** get a quadrant: fine 6, buffered 4, hidden drought 3 (Bikaner, Jhunjhunu, Sikar: normal rain, GW at record lows, all Over-exploited), double drought 3 (Sirohi, Nalgonda, Yadadri Bhuvanagiri). Not classified: GW level-only 349, GW insufficient 319, NE season < 15 days 99.
- **Back-test 2023 (gridded rain Jun–Sep, GW Nov 2023 manual network):** 215 districts classified (fine 128, buffered 40, hidden 27, double 20). Jharkhand 19/24 rain-short, matching its 2023 drought. Hidden drought in Punjab (6) and Rajasthan (7). **Karnataka: only 15/31 districts rain-short, though 223 taluks were declared.** Seasonal departure misses dry-spell droughts like August 2023. Maharashtra, Gujarat and Bihar lack Nov 2023 manual readings on NWDP.
- Groundwater: year-to-year changes of 10 m or more are **normal** (owner, 2026-10-01). No jump flag; only the physical envelope (−5 to 150 m) filters values.

**Status history (6a, 2026-10-01):** snapshots at groundwater cycle ends (Jan 31, May 31, Aug 31, Nov 30) since 2000, so users can look back (e.g. last May = mid-summer, Nov = post-monsoon). Rain = the season current or just completed at the snapshot (IMD official where archived for that exact window, else gridded); `rain_official` now keeps IMD's table on every snapshot/season-end date. Median 577 districts classified per snapshot. Real data gaps: May 2020 and May 2021 have 0 (no pre-monsoon survey during COVID), 2000 (too little prior history), Aug 2012 and Jan 2016 (survey rounds largely missing on NWDP), 2024+ thin. `web/data/status_history.json` is 4.4 MB; split or gzip in Phase 7.

**Open questions:**
1. Current-tier coverage (16 districts): accept, add a provisional GW signal for level-only districts (e.g. fell vs last year / vs decadal mean), or revisit Oracle/WRIS?
2. Rain axis: add a dry-spell / SPI-3 criterion so droughts like Karnataka 2023 aren't missed?

**Phase 4 results (2026-10-01):** IN-GRES 2025-26, figures used as published. 719 districts assessed, 64 not in IN-GRES (carved-out districts still inside their parent, Uttarakhand hills). District categories: Safe 519, Semi-critical 67, Critical 22, Over-exploited 91, Hilly 10, Saline 3; 7 Himachal districts assessed by valley only (no district category). 7,000+ blocks/units fetched. **Hidden stress** (district not Critical/OE but ≥ 1 block is) in **105 districts**, e.g. Pune Safe 63.7% with Shirur Critical 95.7%. Extremes: Sangrur 309%, Jaisalmer 297%, Kolar 186%. Unmatched: 3 Delhi IN-GRES units (Central North, Old Delhi, Outer North) with no LGD equivalent.

**Phase 3 results (2026-10-01):** 42,618 wells (36,887 manual + 5,745 telemetry), 1.4M well-cycles. 1,142 impossible values dropped (outside −5 to 150 m). 701 telemetry↔manual pairs accepted (≤ 50 m, ≥ 2 shared cycles agreeing within 1.5 m).
- **Historical tier:** pre-monsoon trend 2000–2023 for **622 districts (79%)**; PRE/NOV anomaly series for 633. Sanity: Punjab falling (Sangrur 1.1, Barnala 1.0 m/yr; Fazilka rising, matching waterlogging), south Delhi falling 0.4–0.6 m/yr, Marathwada no long-term trend.
- **Current tier (Aug 2026):** full 8, short-record 26, level-only 402, insufficient 347. Percentiles are rare because most telemetry started in 2023 (≤ 3 same-cycle years). Each year adds one; unpaired wells reach the 5-year short tier around 2028. The Oracle/WRIS route (450 districts at full rigour) stays the main upgrade path.

**Phase 2 validation (2026-10-01), SW season Jun 1–Sep 30, our gridded vs IMD published:**
- Subdivision level: median difference 2 percentage points, r = 0.95, 75% within 5 pp. **The method and normals are sound.**
- District level (703 districts): median 9 pp, r = 0.59, 55% within 10 pp, same IMD category for 68%. The gaps come from IMD's few-gauge district average vs our area average, and are largest in hilly or sparsely gauged districts and low-normal districts.
- **Decided:** the headline is IMD's official district figure, archived daily (`pipeline/process/rain_official.py`) with the final snapshot per season; gridded is the fallback and powers history, SPI and the outlook. **Phase 8 must run this daily, or season-final figures are lost** (IMD overwrites its PDFs).
- Front end: when a season is under 7 days old (NE districts on Oct 1), say "season just started" instead of showing a category.
- Automation: `rain_current_daily.parquet` changes daily (0.8 MB), so cache it in Actions instead of committing it.

Phase 1 follow-ups: (a) **Decided 2026-10-01:** keep Rajasthan's 50-district map (9 districts abolished Dec 2024 stay, flagged) and show each source at the level it reports. Never re-apportion data to new boundaries; (b) districts newer than the Dec 2023 map (MP: Pandhurna, Maihar, Mauganj; AP: Markapuram, Polavaram; Gujarat: Vav-Tharad) aren't on it; (c) 64 map districts have no IN-GRES row (carved-out districts and Uttarakhand hills). Phase 4 falls back to the parent or marks them "not assessed". Delhi's IN-GRES units don't match LGD.


1. Buy the domain (hiddendrought.in or similar).
2. Licenses still to confirm: IMD gridded data terms; India Data Portal dataset (`isopen: false`).
3. Later: Oracle/WRIS upgrade for current-tier groundwater; declarations (v2).

## 11. Working rules (for Claude Code)

One phase at a time; stop and summarize at the end of each. Never invent data; if a source fails, log it and stop. Record every source in sources.md. Write tests for aggregation and classification. Commit as Rushikeshay / rushikesh.y.jadhav@gmail.com.
