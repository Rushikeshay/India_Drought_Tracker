"""Status history checks: snapshot dates and agreement with the independent 2023 back-test."""

import unittest
from datetime import date
from pathlib import Path

import pandas as pd

from pipeline.process import history

REPO = Path(__file__).resolve().parents[1]


class TestSnapshots(unittest.TestCase):
    def test_dates_up_to_today(self):
        d = history.snapshot_dates(2026, pd.Timestamp("2026-10-01"))
        self.assertEqual([x[0] for x in d], [date(2026, 1, 31), date(2026, 5, 31), date(2026, 8, 31)])
        self.assertEqual([x[2] for x in d], ["JAN", "PRE", "AUG"])


class TestAgreesWithBacktest(unittest.TestCase):
    def test_nov_2023_matches_backtest_for_sw_districts(self):
        h = pd.read_csv(REPO / "data/processed/status_history.csv", low_memory=False)
        b = pd.read_csv(REPO / "notebooks/phase6/backtest_2023.csv")
        ne = set(pd.read_csv(REPO / "data/reference/ne_monsoon_districts.csv").dist_lgd)
        h = h[(h.snapshot == "2023-11-30") & ~h.dist_lgd.isin(ne)].set_index("dist_lgd")
        b = b[~b.dist_lgd.isin(ne)].set_index("dist_lgd")
        j = h[["quadrant"]].join(b[["quadrant"]], rsuffix="_bt")
        same = (j.quadrant.fillna("-") == j.quadrant_bt.fillna("-"))
        self.assertTrue(same.all(), j[~same].head())


if __name__ == "__main__":
    unittest.main()
