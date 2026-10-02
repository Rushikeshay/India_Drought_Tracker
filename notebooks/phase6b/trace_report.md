# Row-level trace report

Generated 2026-10-01. Districts: Sikar (114), Beed (470).

| Layer | Step | Independent | Pipeline | OK |
|---|---|---|---|---|
| rain | raw IMD grid 2026-08-15 -> Sikar area mean (mm) | 0.191 | 0.191 | ✅ |
| rain | raw IMD yearly grid 2025-07-20 -> Sikar (mm) | 1.827 | 1.827 | ✅ |
| rain | 1971-2020 normal Jun-Sep, Sikar (mm) | 415.1 | 415.1 | ✅ |
| rain | gridded Jun-Sep 2026 actual, Sikar (mm) | 364.5 | 364.5 | ✅ |
| rain | gridded departure % = (actual-normal)/normal | -12 | -12 | ✅ |
| rain | IMD PDF 'SIKAR' last column -> season_2026_SW.csv | -7 | -7 | ✅ |
| rain | season_2026_SW.csv -> rain.json headline (SIKAR, source IMD) | -7 | -7 | ✅ |
| rain | IMD PDF 'BEED' last column -> season_2026_SW.csv | -49 | -49 | ✅ |
| rain | season_2026_SW.csv -> rain.json headline (BEED, source IMD) | -49 | -49 | ✅ |
| groundwater | raw telemetry 'Khatu Shyamji_1' Aug 2026 median x own sign (m) | 41.78 | 41.78 | ✅ |
| groundwater | raw manual 'm:27.3167,75.2950:bai2' Nov 2015 (m) | 15.9 | 15.9 | ✅ |
| groundwater | wells with >= 10 Aug years and an Aug 2026 reading | 5 | 5 | ✅ |
| groundwater | median of per-well percentiles (Aug 2026) | 10 | 10 | ✅ |
| groundwater | low = percentile <= 20 | True | True | ✅ |
| stress | raw IN-GRES stageOfExtraction.total, Sikar (%) | 191.98 | 191.98 | ✅ |
| stress | raw IN-GRES category.total | over_exploited | over_exploited | ✅ |
| stress | worst unit = highest category, then highest stage | DHOND | DHOND | ✅ |
| stress | number of units | 9 | 9 | ✅ |
| idm | raw CDI 2026-09-30 -> Sikar area-weighted mean | -0.09 | -0.09 | ✅ |
| idm | share of Sikar area at D1 or worse (%) | 0.0 | 0.0 | ✅ |
| classify | rain Normal, SPI -0.19, dry spell 3 wk + GW pct 10 -> quadrant | hidden_drought | hidden_drought | ✅ |
| rain | dry spell (longest run of weeks < 50% of normal), Sikar SW 2026 | 3 | 3 | ✅ |
| history | 2026-08-31 snapshot GW percentile = current Aug 2026 | 10 | 10 | ✅ |
| history | 2026-08-31 snapshot rain departure (Jun-Aug, gridded) | -15 | -15.0 | ✅ |
