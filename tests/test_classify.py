"""Phase 6 checks: quadrant rules and when no quadrant is given."""

import unittest

from pipeline.process import classify as c


class TestQuadrant(unittest.TestCase):
    def test_all_four(self):
        self.assertEqual(c.quadrant(False, False), "fine")
        self.assertEqual(c.quadrant(False, True), "hidden_drought")
        self.assertEqual(c.quadrant(True, False), "buffered")
        self.assertEqual(c.quadrant(True, True), "double_drought")

    def test_unknown_axis_gives_none(self):
        self.assertIsNone(c.quadrant(None, True))
        self.assertIsNone(c.quadrant(False, None))


class TestRainAxis(unittest.TestCase):
    def test_deficient_or_worse_is_short(self):
        for cat in ("Deficient", "Large Deficient", "No Rain"):
            self.assertEqual(c.rain_short({"category": cat, "season_days": 122}), (True, None))
        for cat in ("Normal", "Excess", "Large Excess"):
            self.assertEqual(c.rain_short({"category": cat, "season_days": 122}), (False, None))

    def test_young_season_not_classified(self):
        self.assertEqual(c.rain_short({"category": "No Rain", "season_days": 1}), (None, "season_just_started"))

    def test_missing(self):
        self.assertEqual(c.rain_short({}), (None, "no_rain_data"))


class TestGwAxis(unittest.TestCase):
    def test_only_full_and_short_tiers(self):
        self.assertEqual(c.gw_low({"tier": "full", "low": True}), (True, None))
        self.assertEqual(c.gw_low({"tier": "short", "low": False}), (False, None))
        self.assertEqual(c.gw_low({"tier": "level_only"}), (None, "gw_level_only"))
        self.assertEqual(c.gw_low({}), (None, "gw_missing"))


if __name__ == "__main__":
    unittest.main()
