"""JSON for the website: strict (valid JSON only).

Python's json writes NaN/Infinity, which browsers reject (JSON.parse fails, silently
breaking a panel). Every file the site reads goes through dumps(): non-finite
numbers become null, and allow_nan=False makes any leftover a hard error here
instead of in the browser.
"""

from __future__ import annotations

import json
import math

import numpy as np


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return None if not math.isfinite(float(o)) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def dumps(obj, **kw) -> str:
    kw.setdefault("separators", (",", ":"))
    return json.dumps(clean(obj), allow_nan=False, **kw)
