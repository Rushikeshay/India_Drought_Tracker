"""Phase 1 checks: district master, web boundaries, crosswalk logic.

Run: .venv/bin/python -m unittest discover -s tests -v
"""

import json
import unittest
from pathlib import Path

import pandas as pd

from pipeline.process import crosswalk as cw

REPO = Path(__file__).resolve().parents[1]
REF = REPO / "data" / "reference"
WEB = REPO / "web" / "data"


class TestDistrictMaster(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = pd.read_csv(REF / "district_master.csv")

    def test_codes_unique_and_positive(self):
        self.assertTrue(self.m.dist_lgd.is_unique)
        self.assertTrue((self.m.dist_lgd > 0).all())

    def test_count(self):
        self.assertEqual(len(self.m), 783)  # 785 polygons minus 2 PoK

    def test_points_inside_india(self):
        self.assertTrue(self.m.lat.between(6, 38).all() and self.m.lon.between(68, 98).all())

    def test_rajasthan_abolished_flagged(self):
        self.assertEqual(self.m.notes.fillna("").str.contains("abolished").sum(), 9)


class TestWebBoundaries(unittest.TestCase):
    def test_size_and_ids(self):
        p = WEB / "districts.geojson"
        self.assertLess(p.stat().st_size, 2_000_000)
        feats = json.loads(p.read_text())["features"]
        ids = [f["properties"]["lgd"] for f in feats if not f["properties"].get("pok")]
        master = set(pd.read_csv(REF / "district_master.csv").dist_lgd)
        self.assertEqual(set(ids), master)
        self.assertEqual(len(ids), len(set(ids)))


class TestCrosswalkMatching(unittest.TestCase):
    master = pd.DataFrame({
        "dist_lgd": [1, 2, 3, 4],
        "district": ["Gurugram", "Ahmadabad", "Kolar", "Kolkata"],
        "state": ["Haryana", "Gujarat", "Karnataka", "West Bengal"],
    })

    def run_match(self, state, name):
        return cw.match(self.master, pd.DataFrame({"state": [state], "name": [name]}), "test").iloc[0]

    def test_exact_ignores_case_and_punctuation(self):
        r = self.run_match("Karnataka", "KOLAR")
        self.assertEqual((r.dist_lgd, r.method), (3, "exact"))

    def test_alias(self):
        r = self.run_match("HARYANA", "GURGAON")
        self.assertEqual((r.dist_lgd, r.method), (1, "alias"))

    def test_fuzzy(self):
        r = self.run_match("GUJARAT", "AHMEDABAD")
        self.assertEqual((r.dist_lgd, r.method), (2, "fuzzy"))

    def test_no_guess_below_threshold(self):
        r = self.run_match("Karnataka", "Mysuru")
        self.assertEqual(r.method, "unmatched")
        self.assertTrue(pd.isna(r.dist_lgd))

    def test_state_must_match(self):
        r = self.run_match("Bihar", "Kolkata")
        self.assertEqual(r.method, "unmatched_state")

    def test_no_duplicate_one_to_one_codes_in_output(self):
        c = pd.read_csv(REF / "crosswalk_ingres.csv")
        one = c[c.relation == "one"].dropna(subset=["dist_lgd"])
        self.assertTrue(one.dist_lgd.is_unique)


if __name__ == "__main__":
    unittest.main()
