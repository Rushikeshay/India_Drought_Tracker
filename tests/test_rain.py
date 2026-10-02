"""Phase 2 checks: IMD categories, season windows, SPI, grid->district reduction."""

import unittest
from datetime import date

import numpy as np
import pandas as pd
from scipy import sparse

from pipeline.process import rain_current as rc
from pipeline.process.rain import NORMAL_PERIOD, to_districts


class TestCategory(unittest.TestCase):
    def test_boundaries(self):
        cases = {60: "Large Excess", 59: "Excess", 20: "Excess", 19: "Normal", -19: "Normal",
                 -20: "Deficient", -59: "Deficient", -60: "Large Deficient", -99: "Large Deficient",
                 -100: "No Rain"}
        for dep, want in cases.items():
            self.assertEqual(rc.category(dep), want, dep)

    def test_rounding_like_imd(self):
        self.assertEqual(rc.category(-19.4), "Normal")
        self.assertEqual(rc.category(-19.6), "Deficient")

    def test_missing(self):
        self.assertIsNone(rc.category(np.nan))


class TestSeasonWindow(unittest.TestCase):
    def test_sw_in_season(self):
        self.assertEqual(rc.season_window(date(2026, 8, 15), False), ("SW", date(2026, 6, 1), date(2026, 8, 15)))

    def test_sw_after_season_reports_completed_season(self):
        self.assertEqual(rc.season_window(date(2026, 10, 1), False), ("SW", date(2026, 6, 1), date(2026, 9, 30)))

    def test_sw_before_season_reports_last_year(self):
        self.assertEqual(rc.season_window(date(2026, 3, 1), False), ("SW", date(2025, 6, 1), date(2025, 9, 30)))

    def test_ne_switches_on_oct_1(self):
        self.assertEqual(rc.season_window(date(2026, 10, 1), True), ("NE", date(2026, 10, 1), date(2026, 10, 1)))
        self.assertEqual(rc.season_window(date(2026, 9, 30), True)[0], "SW")

    def test_ne_jan_reports_last_ne_season(self):
        self.assertEqual(rc.season_window(date(2027, 1, 5), True), ("NE", date(2026, 10, 1), date(2026, 12, 31)))


class TestSpi(unittest.TestCase):
    def make(self, last_value):
        rng = np.random.default_rng(0)
        rows = []
        for y in range(NORMAL_PERIOD[0], NORMAL_PERIOD[1] + 2):
            for mth in range(1, 13):
                v = rng.gamma(2.0, 50.0)
                if y == NORMAL_PERIOD[1] + 1 and mth == 9:
                    v = last_value
                rows.append({"dist_lgd": 1, "year": y, "month": mth, "mm": v})
        return pd.DataFrame(rows)

    def test_extreme_dry_is_very_negative(self):
        s = rc.spi(self.make(0.0), 1, NORMAL_PERIOD[1] + 1, 9)
        self.assertLess(s[1], -2)

    def test_extreme_wet_is_very_positive(self):
        s = rc.spi(self.make(2000.0), 1, NORMAL_PERIOD[1] + 1, 9)
        self.assertGreater(s[1], 2)

    def test_median_is_near_zero(self):
        m = self.make(0.0)
        base = m[(m.month == 9) & m.year.between(*NORMAL_PERIOD)].mm.median()
        s = rc.spi(self.make(base), 1, NORMAL_PERIOD[1] + 1, 9)
        self.assertLess(abs(s[1]), 0.3)


class TestToDistricts(unittest.TestCase):
    def test_area_weighted_mean_ignores_missing_cells(self):
        # 1 day, 1x3 grid; district 0 covers cell0 (w=1) and cell1 (w=3); cell1 is missing that day
        grid = np.array([[[10.0, np.nan, 40.0]]])
        W = sparse.csr_matrix(np.array([[1.0, 0.0], [3.0, 0.0], [0.0, 2.0]]))
        out = to_districts(grid, W)
        self.assertAlmostEqual(out[0, 0], 10.0)
        self.assertAlmostEqual(out[0, 1], 40.0)

    def test_weighting(self):
        grid = np.array([[[10.0, 20.0, 0.0]]])
        W = sparse.csr_matrix(np.array([[1.0], [3.0], [0.0]]))
        self.assertAlmostEqual(to_districts(grid, W)[0, 0], 17.5)


if __name__ == "__main__":
    unittest.main()
