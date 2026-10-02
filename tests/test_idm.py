"""Phase 5 checks: IDM CDI class edges (copied from IDM's classify())."""

import unittest

import numpy as np

from pipeline.process import idm


class TestClassify(unittest.TestCase):
    def test_edges_match_idm(self):
        v = np.array([0.0, -0.5, -0.79, -0.8, -1.3, -1.31, -1.6, -2.0, -2.5, np.nan])
        want = ["none", "d0", "d0", "d1", "d2", "d2", "d3", "d4", "d4", None]  # -1.3 is not > -1.3, so D2 (IDM rule)
        got = [idm.CLASSES[i] if i >= 0 else None for i in idm.classify(v)]
        self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main()
