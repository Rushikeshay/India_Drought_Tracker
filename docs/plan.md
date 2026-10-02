# India Drought Tracker — Plan (v2)

Repo: github.com/Rushikeshay/India_Drought_Tracker · Updated 2026-10-01 · v1 of this plan is in git history (commit 4a489fe).
Source details, URLs, quirks and test results: [sources.md](sources.md). This file holds the decisions and the status.

## 1. Goal

A public website that shows, for every Indian district, whether **rain** and **groundwater** are adequate, whether **drought was declared**, and what a dry next year would mean. Audience: intermediaries (NGOs, extension officers, journalists, district officials).

Core idea: drought declaration is gated on rainfall (Drought Manual 2020), so:
- **Hidden drought:** normal rain but depleted groundwater, so no declaration.
- **Buffered:** poor rain but good groundwater.

## 2. Two tiers

| Tier | Period | Layers | What it answers |
|---|---|---|---|
| **Historical** | ~2000–2023 | Rain, groundwater trend, declarations, IN-GRES stress | Long-term pattern for the district. Context where current data is thin. |
| **Current** | 2024–now | Rain season-to-date, latest groundwater level, current declarations, ENSO outlook | How the district is doing right now. |

## 3. Coverage without an India IP (measured 2026-10-01, 785 LGD districts)

| Layer | Historical 2000–2023 | Current 2024–now |
|---|---|---|
| Rain (IMD gridded) | 100% | 100% (daily) |
| GW: ≥ 1 well | 91% | 57% live in the last 60 days · 76% with any 2024+ reading |
| GW: ≥ 3 wells, ≥ 5 yrs history | 85% | 2% (telemetry only) to 23% (if paired with old manual wells) |
| GW: ≥ 5 wells, ≥ 10 yrs (v1 rule) | 78% | ≤ 9% |
| Declarations | Not available yet (§6) | Not available yet |

Reproduce with `notebooks/phase0/coverage.py`.

## 4. Data sources (decided)

| Layer | Source | Access | Refresh |
|---|---|---|---|
| Rain | IMD 0.25° gridded: yearly files (1901–last year) + real-time daily | POST to imdpune.gov.in; works from any IP | Daily; re-fetch the last 7 days (newest file may be preliminary) |
| GW history | **NWDP** CGWB manual quarterly CSVs, 1991–2025 (most states end 2023–24) | nwdp.nwic.gov.in CKAN; any IP; includes LGD codes | One-time + yearly |
| GW current | **NWDP** CGWB telemetry six-hourly, 2026–2030 files (~3,500 live wells) | Same; 2-day lag | Daily |
| GW stress | IN-GRES, **2025-2026** edition, district + block | Open JSON API | Yearly |
| Detected drought (cross-check) | IIT-GN India Drought Monitor (CDI, SPI, soil moisture; 740 districts by name) | GitHub raw files | Weekly. **No license; ask before republishing** |
| ENSO | NOAA CPC strength-probability table (RONI-based) | HTML table | Monthly (2nd Thursday) |
| NMME rain terciles | IRI Data Library | Reachable | Monthly (Phase 9) |
| Declarations | See §6 | — | — |
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

## 6. Drought declarations (moved up from v2)

No national machine-readable dataset exists; states publish their own notifications. The IDM data tables are a **detected** index (D0–D4 area %), not declarations.
- **2000–2017:** IIT Gandhinagar ("Drought detection and declaration in India", *Water Security* 2021) compared declared and detected drought for all districts. **Email the lab** to ask for the declarations data and for permission to reuse IDM data.
- **2018–now:** hand-compiled CSV `data/reference/declarations.csv` (state, district, tehsil, season, year, date, order URL). Start with drought-prone states (Maharashtra, Karnataka, Andhra Pradesh, Telangana, Rajasthan, Gujarat, Madhya Pradesh).
- Show declared vs detected (rain deficit, IDM CDI, groundwater) side by side. That gap is the point of the site.

## 7. Classification (current tier)

| | GW OK | GW low |
|---|---|---|
| **Rain OK** | Fine | Hidden drought |
| **Rain short** (IMD Deficient or worse, season-to-date) | Buffered | Double drought |

Secondary marks: GW confidence tier, IN-GRES category and worst block, declared yes/no, data age. NE-monsoon districts (Tamil Nadu, Puducherry, coastal AP, Rayalaseema, south interior Karnataka, Kerala) switch to the Oct–Dec season on Oct 1.

## 8. Phases and status

| # | Phase | Status | Done when |
|---|---|---|---|
| 0 | Access tests | ✅ **Done** (WRIS blocked → NWDP) | Probes from laptop + Actions; sources.md; coverage measured |
| 1 | Boundaries + district master | ⏭ **Next.** File downloaded | `districts.topojson` < 2 MB, `district_master.csv` (LGD), crosswalks to IN-GRES/IDM names |
| 2 | Rainfall pipeline | — | Season-to-date departure + SPI per district; matches IMD district pages within a few % |
| 3 | Groundwater pipeline (NWDP) | — | History + telemetry merged; signs, envelope, pairing, tiers; sane for Punjab, Marathwada, Delhi |
| 4 | Stress layer (IN-GRES) | — | 2025-26 edition joined incl. worst block; unmatched listed |
| 5 | Declarations | — | IIT-GN emailed; CSV schema; ≥ 1 state compiled 2018–now |
| 6 | Classification + validation | — | Both tiers; unit tests; back-test 2023 vs known droughts |
| 7 | Front end v1 | — | Map, district panel, hidden-drought table, methods page; phone + laptop |
| 8 | Automation | — | `refresh.yml` daily on Actions, unattended for 2 weeks |
| 9 | Outlook | — | Scenario engine + ENSO/NMME; back-test |
| 10 | Launch + feedback | — | 3–5 intermediaries try it |

## 9. Architecture (unchanged)

`pipeline/` (sources → process → outlook → `run.py`) → `web/data/*.json` (committed) → GitHub Pages (plain HTML/JS + D3, no build). Raw downloads go in `data/raw/` (gitignored). Python 3.11 in `.venv` via uv; dependencies are in `requirements.txt` only (pandas, geopandas, xarray, imdlib, duckdb, requests). Ask before adding any others. **Note:** parquet output needs `pyarrow`, which hasn't been approved yet.

## 10. Open items

1. Email IIT-GN: declarations 2000–2017 and IDM reuse terms.
2. Site name and domain.
3. Approve `pyarrow` (parquet) or keep CSV.
4. Licenses still to confirm: IMD gridded data terms; India Data Portal dataset (`isopen: false`).
5. Later: Oracle/WRIS upgrade for current-tier groundwater.

## 11. Working rules (for Claude Code)

One phase at a time; stop and summarize at the end of each. Never invent data; if a source fails, log it and stop. Record every source in sources.md. Write tests for aggregation and classification. Commit as Rushikeshay / rushikesh.y.jadhav@gmail.com.
