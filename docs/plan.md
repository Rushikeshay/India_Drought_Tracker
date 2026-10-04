# India Drought & Groundwater Watch — Plan (v2)

Tagline / web address: **Hidden Drought** (e.g. hiddendrought.in, domain not yet bought).

Repo: github.com/Rushikeshay/India_Drought_Tracker · Updated 2026-10-04 · v1 of this plan is in git history (commit 4a489fe).
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
| 6a | Status history (snapshots) | ✅ **Done 2026-10-01**: Jan/May/Aug/Nov from 2000, 107 snapshots, median 637 districts classified per snapshot |
| 6b | Row-level trace (backend accuracy check) | ✅ **Done 2026-10-01**: 23 steps for Sikar and Beed recomputed independently from raw files, all match (`notebooks/phase6b/trace_report.md`, `tests/test_trace.py`). Found and fixed: 61 placeholder `NaN NaN NaN` rows in IDM files |
| 7 | Front end v1 | ✅ **Built 2026-10-01** (awaiting review): map (5 layers), district panel with charts + timeline, history date picker (107 snapshots), sortable table + CSV, methods page, dark mode, mobile. Colours validated (all-pairs, light + dark). Publish via `.github/workflows/pages.yml` (needs Pages source = GitHub Actions) | Map, district panel, hidden-drought table, methods page; phone + laptop |
| 8 | Automation | 🟡 **Built 2026-10-04**, on watch: `pipeline/run.py` + `.github/workflows/refresh.yml`; clean-checkout trial passed (all 7 steps, 13 min). See §10 | `refresh.yml` daily on Actions, unattended for 2 weeks (to 2026-10-18) |
| 9 | Outlook | ⏭ **Next** (after the Phase 8 watch) | Scenario engine + ENSO/NMME; back-test |
| 10 | Launch + feedback | — | 3–5 intermediaries try it |

## 9. Architecture (unchanged)

`pipeline/` (sources → process → outlook → `run.py`) → `web/data/*.json` (committed) → GitHub Pages (plain HTML/JS + D3, no build). `run.py` is run daily by `.github/workflows/refresh.yml`, which then publishes through `pages.yml`. Raw downloads go in `data/raw/` (gitignored). Python 3.11 in `.venv` via uv; dependencies are in `requirements.txt` only (pandas, geopandas, xarray, imdlib, duckdb, requests). Ask before adding any others. `pyarrow` approved 2026-10-01 (parquet). Tests use stdlib `unittest`: `.venv/bin/python -m unittest discover -s tests -t .`

## 10. Open items

**Phase 8 automation (2026-10-04):**
- **Schedule:** full run daily at 12:30 UTC (18:00 IST); a second run at 02:30 UTC (08:00 IST) only archives IMD's district rainfall table, because IMD overwrites it daily and season-final figures would be lost.
- **Steps** (`python -m pipeline.run`): rain_official → rain → groundwater → idm → classify → history → check. A failed source keeps that layer's previous files and the other layers still update; nothing is filled in. The job ends red if any step failed (GitHub emails the owner). `web/data/run.json` records each run.
- **What gets committed by the run:** `web/data/` (only if the publish check and the tests pass) and `data/processed/imd_official/` (always). Processed parquet files are rebuilt in the runner and not committed, so the repo does not grow by megabytes a day.
- **No raw history on the runner.** The 2.9 GB in `data/raw/` stays on the laptop. Groundwater (`--incremental`), weekly rain and the drought index build on the committed processed files and download only what changes: all manual NWDP files (180 MB), current-period telemetry (390 MB), new IDM weeks, the last 7 days of IMD grids. Checked on the laptop: incremental groundwater and IDM output is identical to a full rebuild.
- **Cache (Actions):** NWDP downloads, this year's daily rain, full-resolution boundaries. Losing the cache makes a run slower, not different. `rain_current_daily.parquet` is committed as a seed, because without it a cold start downloads every day of the year (about 25 s each, 2 hours).
- **Publish check** (`pipeline/validate/publish.py`): valid JSON, 783 districts, coverage floors (rain 700, drought index 700, stress 650, groundwater 250), all history files present.
- **Library versions pinned** in `requirements.txt` (pandas 3.0.6 etc.).
- **Not in the daily run:** IN-GRES stress (yearly; run `stress` and `stress_history` by hand for a new edition).
- **Open, before 2026-12-31:** year rollover. On Jan 1 the daily rain file restarts for 2027 and `rain_monthly.parquet` ends at 2025, so the Oct–Dec 2026 season would lose its gridded figures until the 2026 yearly file is reduced (`rain history --end 2026`, needs the laptop). Needs a small change so the previous year's daily file is kept until then.
- **Open:** after long gaps between laptop rebuilds, re-commit the processed files so cold starts stay short (the seed and the IDM base only move forward when committed).

**Phase 6 results (2026-10-01):**
- **Current (rain = SW 2026 / NE season, GW = Aug 2026):** only **16 districts** get a quadrant: fine 6, buffered 4, hidden drought 3 (Bikaner, Jhunjhunu, Sikar: normal rain, GW at record lows, all Over-exploited), double drought 3 (Sirohi, Nalgonda, Yadadri Bhuvanagiri). Not classified: GW level-only 349, GW insufficient 319, NE season < 15 days 99.
- **Back-test 2023 (gridded rain Jun–Sep, GW Nov 2023 manual network):** 215 districts classified (fine 128, buffered 40, hidden 27, double 20). Jharkhand 19/24 rain-short, matching its 2023 drought. Hidden drought in Punjab (6) and Rajasthan (7). **Karnataka: only 15/31 districts rain-short, though 223 taluks were declared.** Seasonal departure misses dry-spell droughts like August 2023. Maharashtra, Gujarat and Bihar lack Nov 2023 manual readings on NWDP.
- Groundwater: year-to-year changes of 10 m or more are **normal** (owner, 2026-10-01). No jump flag; only the physical envelope (−5 to 150 m) filters values.

**Status history (6a, 2026-10-01):** snapshots at groundwater cycle ends (Jan 31, May 31, Aug 31, Nov 30) since 2000, so users can look back (e.g. last May = mid-summer, Nov = post-monsoon). Rain = the season current or just completed at the snapshot (IMD official where archived for that exact window, else gridded); `rain_official` now keeps IMD's table on every snapshot/season-end date. Median 637 districts classified per snapshot (577 before the provisional groundwater tier). Real data gaps: May 2020 and May 2021 have 0 (no pre-monsoon survey during COVID), 2000 (too little prior history), Aug 2012 and Jan 2016 (survey rounds largely missing on NWDP), 2024+ thin. `web/data/status_history.json` is 4.4 MB; split or gzip in Phase 7.

**Decided 2026-10-01 (owner):**
1. **Provisional GW tier:** ≥ 1 well with ≥ 2 same-cycle years → percentile vs that short record; quadrant shown as *provisional*. Current classified/provisional: 342 326.
2. **Rain short = deviation OR SPI OR dry spell** (Drought Manual 2020 §3.2.1). Deviation = IMD category Deficient or worse. SPI over the season window ≤ −1.0. Dry spell = ≥ 4 consecutive standard weeks < 50% of normal (manual: "usually 4 weeks", 3 for light soils). Weeks count only once the normal is meaningful (≥ 50% of the season's mean weekly normal), standing in for "after onset". Calibration 1971–2025 SW seasons: 3 weeks fired in 41% of district-seasons, 4 weeks in 19%; overall rain-short 35% (2009 61%, 2019 25%). Karnataka 2023 now 27/31 districts (was 15), matching 223 declared taluks. Gujarat 2023 shows 30/33 short via a 5-week August dry spell despite season +8%; the site must show the reason. The manual's Table 3.11 combination matrix is an image in the available PDF and was not used.

**Phase 4 results (2026-10-01):** IN-GRES 2025-26, figures used as published. 719 districts assessed, 64 not in IN-GRES (carved-out districts still inside their parent, Uttarakhand hills). District categories: Safe 519, Semi-critical 67, Critical 22, Over-exploited 91, Hilly 10, Saline 3; 7 Himachal districts assessed by valley only (no district category). 7,000+ blocks/units fetched. **Hidden stress** (district not Critical/OE but ≥ 1 block is) in **105 districts**, e.g. Pune Safe 63.7% with Shirur Critical 95.7%. Extremes: Sangrur 309%, Jaisalmer 297%, Kolar 186%. Unmatched: 3 Delhi IN-GRES units (Central North, Old Delhi, Outer North) with no LGD equivalent.

**Phase 7 review fixes (2026-10-01):** stress layer now follows the date (IN-GRES editions 2019-20 and 2021-22 to 2025-26, district level; 2016-17 excluded because 446/668 rows are "hilly"); "No category" → "No data" + short reason; notice when a layer has no data for a date (IDM before Jul 2021, stress before 2020); theme persists across pages (js/theme.js); table column definitions linked to Methods; Methods cites sources inline.

**Phase 3 results (2026-10-01):** 42,618 wells (36,887 manual + 5,745 telemetry), 1.4M well-cycles. 1,142 impossible values dropped (outside −5 to 150 m). 701 telemetry↔manual pairs accepted (≤ 50 m, ≥ 2 shared cycles agreeing within 1.5 m).
- **Historical tier:** pre-monsoon trend 2000–2023 for **622 districts (79%)**; PRE/NOV anomaly series for 633. Sanity: Punjab falling (Sangrur 1.1, Barnala 1.0 m/yr; Fazilka rising, matching waterlogging), south Delhi falling 0.4–0.6 m/yr, Marathwada no long-term trend.
- **Current tier (Aug 2026):** full 8, short-record 26, level-only 402, insufficient 347. Percentiles are rare because most telemetry started in 2023 (≤ 3 same-cycle years). Each year adds one; unpaired wells reach the 5-year short tier around 2028. The Oracle/WRIS route (450 districts at full rigour) stays the main upgrade path.

**Phase 2 validation (2026-10-01), SW season Jun 1–Sep 30, our gridded vs IMD published:**
- Subdivision level: median difference 2 percentage points, r = 0.95, 75% within 5 pp. **The method and normals are sound.**
- District level (703 districts): median 9 pp, r = 0.59, 55% within 10 pp, same IMD category for 68%. The gaps come from IMD's few-gauge district average vs our area average, and are largest in hilly or sparsely gauged districts and low-normal districts.
- **Decided:** the headline is IMD's official district figure, archived daily (`pipeline/process/rain_official.py`) with the final snapshot per season; gridded is the fallback and powers history, SPI and the outlook. **Phase 8 must run this daily, or season-final figures are lost** (IMD overwrites its PDFs).
- Front end: when a season is under 7 days old (NE districts on Oct 1), say "season just started" instead of showing a category.
- Automation: `rain_current_daily.parquet` changes daily (0.8 MB), so the daily run caches it in Actions; the committed copy is only a seed (see Phase 8 above).

Phase 1 follow-ups: (a) **Decided 2026-10-01:** keep Rajasthan's 50-district map (9 districts abolished Dec 2024 stay, flagged) and show each source at the level it reports. Never re-apportion data to new boundaries; (b) districts newer than the Dec 2023 map (MP: Pandhurna, Maihar, Mauganj; AP: Markapuram, Polavaram; Gujarat: Vav-Tharad) aren't on it; (c) 64 map districts have no IN-GRES row (carved-out districts and Uttarakhand hills). Phase 4 falls back to the parent or marks them "not assessed". Delhi's IN-GRES units don't match LGD.


1. Buy the domain (hiddendrought.in or similar).
2. Licenses still to confirm: IMD gridded data terms; India Data Portal dataset (`isopen: false`).
3. Later: Oracle/WRIS upgrade for current-tier groundwater; declarations (v2).

## 11. Working rules (for Claude Code)

One phase at a time; stop and summarize at the end of each. Never invent data; if a source fails, log it and stop. Record every source in sources.md. Write tests for aggregation and classification. Commit as Rushikeshay / rushikesh.y.jadhav@gmail.com.
