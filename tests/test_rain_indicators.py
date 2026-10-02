"""Dry spell / season SPI / combined rain rule (Manual for Drought Management 2020)."""

import unittest
from datetime import date

import pandas as pd

from pipeline.process import rain_indicators as ri


class TestWeeks(unittest.TestCase):
    def test_only_full_weeks_inside_window(self):
        w = ri.window_weeks(date(2026, 6, 1), date(2026, 9, 30))
        self.assertEqual(w[0], (2026, 23))   # SMW 22 starts May 28 -> excluded
        self.assertEqual(w[-1], (2026, 39))  # SMW 39 = Sep 24-30

    def test_longest_run(self):
        self.assertEqual(ri.longest_run([True, True, False, True, True, True, False]), 3)


class TestDrySpell(unittest.TestCase):
    def make(self, actual_by_week):
        wks = [w for _, w in ri.window_weeks(date(2026, 6, 1), date(2026, 9, 30))]
        weekly = pd.DataFrame({"year": 2026, "week": wks, "dist_lgd": 1, "mm": [actual_by_week.get(w, 50.0) for w in wks]})
        normal = pd.DataFrame({"week": wks, "dist_lgd": 1, "mm": 50.0})
        return ri.dry_spells(weekly, normal, date(2026, 6, 1), date(2026, 9, 30))[1]

    def test_four_dry_weeks(self):
        self.assertEqual(self.make({30: 10, 31: 0, 32: 20, 33: 24}), 4)

    def test_half_of_normal_is_not_dry(self):
        self.assertEqual(self.make({30: 25, 31: 25}), 0)  # < 50% needed; 25 of 50 is exactly 50%

    def test_ineligible_weeks_break_runs(self):
        wks = [w for _, w in ri.window_weeks(date(2026, 6, 1), date(2026, 9, 30))]
        weekly = pd.DataFrame({"year": 2026, "week": wks, "dist_lgd": 1, "mm": 0.0})
        normal = pd.DataFrame({"week": wks, "dist_lgd": 1, "mm": [1.0 if w in (23, 24, 25) else 50.0 for w in wks]})
        # pre-onset weeks 23-25 have tiny normals: not counted, so the run starts at week 26
        self.assertEqual(ri.dry_spells(weekly, normal, date(2026, 6, 1), date(2026, 9, 30))[1], len(wks) - 3)


class TestRule(unittest.TestCase):
    def test_any_of_three(self):
        self.assertEqual(ri.rain_short("Normal", -0.2, 1), (False, []))
        self.assertEqual(ri.rain_short("Deficient", -0.2, 1), (True, ["deviation"]))
        self.assertEqual(ri.rain_short("Normal", -1.0, 1), (True, ["spi"]))
        self.assertEqual(ri.rain_short("Normal", 0.3, 4), (True, ["dry_spell"]))
        self.assertEqual(ri.rain_short("Normal", 0.3, 3), (False, []))

    def test_no_data(self):
        self.assertEqual(ri.rain_short(None, None, None), (None, []))


if __name__ == "__main__":
    unittest.main()
