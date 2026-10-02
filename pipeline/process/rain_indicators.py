"""Rain axis indicators, following the Manual for Drought Management 2020 (§3.2.1):
the first drought trigger uses "RF deviation or SPI or Dry Spell".

  RF deviation  IMD category Deficient or worse (<= -20%) for the season window
  SPI           SPI over the same season window (n months) <= SPI_DRY (-1.0, "moderately dry");
                only when the window is whole months
  Dry spell     "consecutive 3-4 weeks after the due date for the onset of monsoon with
                rainfall less than 50% of the normal in each of the weeks" (manual p.33).
                Weeks = IMD standard meteorological weeks fully inside the window. A week only
                counts once its normal is meaningful (>= ELIGIBLE_FRAC x the window's mean weekly
                normal), as a data-driven stand-in for "after the due date of onset"; ineligible or
                missing weeks break a run. Dry spell = longest run >= DRY_SPELL_WEEKS (4; see constant).

rain short = any of the three. The manual's Table 3.11 (exact combination matrix) is an image
in the available PDF and was not used; "any of the three" follows the manual's text.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from pipeline.process.rain_current import spi
from pipeline.process.rain_weekly import smw

SPI_DRY = -1.0
DRY_WEEK_FRAC = 0.5
ELIGIBLE_FRAC = 0.5
DRY_SPELL_WEEKS = 4  # manual: "usually 4 weeks (upto 3 weeks incase of light soils)"; 3 fired in 41% of all seasons 1971-2025, 4 in 19%
SHORT_CATEGORIES = {"Deficient", "Large Deficient", "No Rain"}


def window_weeks(start: date, end: date) -> list[tuple[int, int]]:
    """(year, SMW) pairs whose 7 days lie fully inside [start, end] (week 52 may be 8-9 days)."""
    out = []
    d = start
    while d <= end:
        wk = int(smw(pd.DatetimeIndex([d]))[0])
        ws = date(d.year, 1, 1) + timedelta(days=7 * (wk - 1))
        we = date(d.year, 12, 31) if wk == 52 else ws + timedelta(days=6)
        if ws >= start and we <= end and (d.year, wk) not in out:
            out.append((d.year, wk))
        d = we + timedelta(days=1)
    return out


def longest_run(flags: list[bool]) -> int:
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


def dry_spells(weekly: pd.DataFrame, wnormal: pd.DataFrame, start: date, end: date) -> pd.Series:
    """Longest qualifying dry run (weeks) per district for the window."""
    wks = window_weeks(start, end)
    if not wks:
        return pd.Series(dtype=float)
    keys = pd.MultiIndex.from_tuples(wks, names=["year", "week"])
    act = weekly.set_index(["year", "week", "dist_lgd"]).mm.unstack().reindex(keys)
    nrm = wnormal.set_index(["week", "dist_lgd"]).mm.unstack().reindex([w for _, w in wks])
    nrm.index = keys
    out = {}
    for code in nrm.columns:
        n = nrm[code].to_numpy(float)
        a = act[code].to_numpy(float) if code in act.columns else np.full(len(n), np.nan)
        mean_n = np.nanmean(n)
        if not np.isfinite(mean_n) or mean_n <= 0:
            continue
        eligible = n >= ELIGIBLE_FRAC * mean_n
        dry = eligible & ~np.isnan(a) & (a < DRY_WEEK_FRAC * n)
        out[code] = longest_run(list(dry))
    return pd.Series(out)


def season_spi(monthly: pd.DataFrame, start: date, end: date) -> pd.Series:
    """SPI over the window's months; empty unless the window is whole calendar months."""
    whole = start.day == 1 and (end + timedelta(days=1)).day == 1
    if not whole:
        return pd.Series(dtype=float)
    n = (end.year - start.year) * 12 + end.month - start.month + 1
    return spi(monthly[["dist_lgd", "year", "month", "mm"]], n, end.year, end.month)


def rain_short(category: str | None, spi_value: float | None, dry_weeks: int | None) -> tuple[bool | None, list[str]]:
    reasons = []
    if category in SHORT_CATEGORIES:
        reasons.append("deviation")
    if spi_value is not None and not pd.isna(spi_value) and spi_value <= SPI_DRY:
        reasons.append("spi")
    if dry_weeks is not None and not pd.isna(dry_weeks) and dry_weeks >= DRY_SPELL_WEEKS:
        reasons.append("dry_spell")
    if category is None and spi_value is None and dry_weeks is None:
        return None, []
    return bool(reasons), reasons
