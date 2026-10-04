"""End-to-end row trace (pipeline/validate/trace.py): every independent recomputation
must match the pipeline output. Steps whose raw files are absent are skipped inside.
The whole trace needs the raw history that only exists on the build machine, so it is
skipped on a clean checkout (the daily run on GitHub Actions)."""

import unittest
from pathlib import Path

from pipeline.validate import trace

REPO = Path(__file__).resolve().parents[1]
HAS_RAW = (REPO / "data/raw/imd/reduced").is_dir() and (REPO / "data/reference/districts.parquet").exists()


@unittest.skipUnless(HAS_RAW, "raw history not on this machine")
class TestTrace(unittest.TestCase):
    def test_all_steps_match(self):
        res = trace.run()
        self.assertGreaterEqual(len(res), 10)
        bad = [r for r in res if not r["ok"]]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
