"""Publish check: passes on the committed site data, fails when a layer collapses."""

import copy
import json
import unittest
from pathlib import Path

from pipeline.validate import publish

WEB = Path(__file__).resolve().parents[1] / "web" / "data"


class TestPublishCheck(unittest.TestCase):
    def test_committed_data_passes(self):
        self.assertEqual(publish.problems(WEB), [])

    def test_missing_layer_is_caught(self):
        doc = copy.deepcopy(json.loads((WEB / "status.json").read_text()))
        for r in doc["districts"].values():
            r["rain"] = {"category": None}
        p = publish.status_problems(doc)
        self.assertEqual(len(p), 1)
        self.assertIn("rain", p[0])

    def test_wrong_district_count_is_caught(self):
        doc = json.loads((WEB / "status.json").read_text())
        doc["districts"].pop(next(iter(doc["districts"])))
        self.assertTrue(any("782" in x for x in publish.status_problems(doc)))

    def test_nan_is_not_valid(self):
        with self.assertRaises(ValueError):
            json.loads('{"a": NaN}', parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))


if __name__ == "__main__":
    unittest.main()
