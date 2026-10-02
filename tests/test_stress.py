"""Phase 4 checks: IN-GRES field extraction and the 'total' row filter."""

import unittest

from pipeline.process import stress
from pipeline.sources import ingres


class TestFields(unittest.TestCase):
    row = {"locationName": "Pune", "category": {"total": "safe", "poor_quality": "over_exploited"},
           "stageOfExtraction": {"total": 63.7277}, "rechargeData": {"total": {"total": 197510.8}},
           "totalGWAvailability": {"total": 183100.95}, "draftData": {"total": {"total": 118443.9}}}

    def test_values_as_published(self):
        f = stress.fields(self.row)
        self.assertEqual(f["category"], "Safe")
        self.assertEqual(f["stage_pct"], 63.73)
        self.assertEqual((f["recharge_ham"], f["extractable_ham"], f["extraction_ham"]), (197510.8, 183100.95, 118443.9))
        self.assertEqual(f["poor_quality_category"], "Over-exploited")

    def test_saline_and_hilly_labels(self):
        self.assertEqual(stress.fields({"category": {"total": "salinity"}})["category"], "Saline")
        self.assertEqual(stress.fields({"category": "Hilly Area"})["category"], "Hilly area")

    def test_missing_numbers_are_none(self):
        f = stress.fields({"locationName": "X", "category": None})
        self.assertIsNone(f["stage_pct"])
        self.assertIsNone(f["category"])


class TestTotalRow(unittest.TestCase):
    def test_total_row_dropped(self):
        rows = [{"locationName": "Pune", "locationUUID": "a"}, {"locationName": "total", "locationUUID": None}]
        self.assertEqual([r["locationName"] for r in ingres.real_rows(rows)], ["Pune"])


if __name__ == "__main__":
    unittest.main()
