"""Every JSON/GeoJSON file the website loads must be strict JSON (no NaN/Infinity)."""

import json
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"


def _reject(c):
    raise ValueError(f"non-standard JSON constant {c}")


class TestWebJson(unittest.TestCase):
    def test_all_site_json_is_strict(self):
        files = list((WEB / "data").glob("*.json")) + list((WEB / "data").glob("*.geojson")) + \
            list((WEB / "data" / "history").glob("*.json")) + [WEB / "i18n" / "en.json"]
        self.assertGreater(len(files), 10)
        for p in files:
            with self.subTest(file=p.name):
                json.loads(p.read_text(), parse_constant=_reject)


if __name__ == "__main__":
    unittest.main()
