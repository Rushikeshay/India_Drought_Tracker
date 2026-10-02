"""Phase 3 checks: cycles, percentile direction, trend, signs, pairing rule."""

import unittest

import numpy as np
import pandas as pd

from pipeline.process import groundwater as gw


class TestCycles(unittest.TestCase):
    def test_current_cycle(self):
        self.assertEqual(gw.current_cycle(pd.Timestamp("2026-10-01")), (2026, "AUG"))
        self.assertEqual(gw.current_cycle(pd.Timestamp("2026-12-05")), (2026, "NOV"))
        self.assertEqual(gw.current_cycle(pd.Timestamp("2027-01-15")), (2026, "NOV"))
        self.assertEqual(gw.current_cycle(pd.Timestamp("2027-02-01")), (2027, "JAN"))
        self.assertEqual(gw.current_cycle(pd.Timestamp("2026-06-01")), (2026, "PRE"))

    def test_month_mapping_covers_manual_campaigns(self):
        self.assertEqual([gw.CYCLE_OF_MONTH[m] for m in (1, 4, 5, 8, 11)], ["JAN", "PRE", "PRE", "AUG", "NOV"])


class TestPercentile(unittest.TestCase):
    def test_deepest_on_record_is_zero(self):
        self.assertEqual(gw.percentile_low(np.array([5.0, 6.0, 7.0]), 9.0), 0.0)

    def test_shallowest_on_record_is_100(self):
        self.assertEqual(gw.percentile_low(np.array([5.0, 6.0, 7.0]), 4.0), 100.0)

    def test_ties_count_half(self):
        self.assertEqual(gw.percentile_low(np.array([5.0, 6.0]), 6.0), 25.0)  # ties the deepest


class TestTrend(unittest.TestCase):
    def test_sen_slope_ignores_outlier(self):
        y = np.arange(2000, 2012, dtype=float)
        v = 10 + 0.5 * (y - 2000)
        v[5] = 100
        self.assertAlmostEqual(gw.sen_slope(y, v), 0.5)


class TestSigns(unittest.TestCase):
    def test_telemetry_negative_down_is_flipped_manual_is_not(self):
        c = pd.DataFrame({"well_id": ["t:a", "t:a", "t:b", "m:c", "m:c"], "raw": [-5.0, -6.0, 4.0, -1.0, -2.0]})
        s = gw.assign_signs(c)
        self.assertEqual((s["t:a"], s["t:b"], s["m:c"]), (-1, 1, 1))


class TestWellIdentity(unittest.TestCase):
    def test_suffix_dropped_but_nested_piezometers_kept_apart(self):
        lat, lon = pd.Series([20.1, 20.1, 20.1]), pd.Series([73.5, 73.5, 73.5])
        ids = gw._well_id("manual", lat, lon, pd.Series(["Aad (Bk)_1", "Aad (Bk)", "Kalol Pz_II"]))
        self.assertEqual(ids[0], ids[1])
        self.assertNotEqual(ids[0], ids[2])


if __name__ == "__main__":
    unittest.main()
