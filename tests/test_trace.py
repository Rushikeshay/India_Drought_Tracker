"""End-to-end row trace (pipeline/validate/trace.py): every independent recomputation
must match the pipeline output. Steps whose raw files are absent are skipped inside."""

import unittest

from pipeline.validate import trace


class TestTrace(unittest.TestCase):
    def test_all_steps_match(self):
        res = trace.run()
        self.assertGreaterEqual(len(res), 10)
        bad = [r for r in res if not r["ok"]]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
