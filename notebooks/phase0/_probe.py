"""Shared helpers for Phase 0 access probes.

Each probe script records every HTTP step (URL, status, time, size, error) and
writes one JSON file per source to notebooks/phase0/results/<where>/<source>.json,
where <where> is "gha" on a GitHub Actions runner and "laptop" otherwise.
Raw samples go to data/raw/phase0/<where>/ (gitignored).

A failed step is recorded and the probe stops: later steps depend on earlier
ones, and we never substitute made-up values.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[2]
WHERE = os.environ.get("PROBE_WHERE") or ("gha" if os.environ.get("GITHUB_ACTIONS") == "true" else "laptop")
RESULTS_DIR = REPO / "notebooks" / "phase0" / "results" / WHERE
RAW_DIR = REPO / "data" / "raw" / "phase0" / WHERE

UA = "Mozilla/5.0 (India water stress tool; Phase 0 access probe)"


class ProbeFailed(Exception):
    pass


class Probe:
    def __init__(self, source: str):
        self.source = source
        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA
        self.record: dict = {
            "source": source,
            "where": WHERE,
            "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "egress": self._egress(),
            "steps": [],
            "findings": {},
            "status": "running",
        }
        RAW_DIR.mkdir(parents=True, exist_ok=True)

    def _egress(self) -> dict:
        # Country of the outbound IP, because several gov hosts filter by it.
        try:
            r = requests.get("https://ipinfo.io/json", timeout=10)
            j = r.json()
            return {"country": j.get("country"), "org": j.get("org")}
        except Exception as exc:  # not fatal
            return {"error": repr(exc)}

    def http(self, name: str, method: str, url: str, *, required: bool = True, **kw) -> requests.Response | None:
        kw.setdefault("timeout", 60)
        step = {"name": name, "method": method, "url": url}
        if "params" in kw:
            step["params"] = kw["params"]
        if "json" in kw:
            step["json"] = kw["json"]
        t0 = time.monotonic()
        try:
            r = self.session.request(method, url, **kw)
            step.update(
                status=r.status_code,
                seconds=round(time.monotonic() - t0, 2),
                bytes=len(r.content),
                content_type=r.headers.get("Content-Type"),
                ok=r.ok,
            )
            if not r.ok:
                step["body_head"] = r.text[:500]
        except Exception as exc:
            step.update(ok=False, seconds=round(time.monotonic() - t0, 2), error=repr(exc))
            r = None
        self.record["steps"].append(step)
        print(f"[{self.source}] {name}: {step.get('status', step.get('error'))} in {step['seconds']}s")
        if required and (r is None or not r.ok):
            raise ProbeFailed(f"{name} failed: {step.get('status') or step.get('error')}")
        return r

    def note(self, key: str, value) -> None:
        self.record["findings"][key] = value
        print(f"[{self.source}] {key}: {value}")

    def save_raw(self, filename: str, content: bytes | str) -> Path:
        p = RAW_DIR / filename
        p.write_bytes(content if isinstance(content, bytes) else content.encode())
        return p

    def finish(self, exc: BaseException | None = None) -> int:
        if exc is None:
            self.record["status"] = "ok"
        else:
            self.record["status"] = "failed"
            self.record["error"] = repr(exc)
            if not isinstance(exc, ProbeFailed):
                self.record["traceback"] = traceback.format_exc()
        self.record["finished_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out = RESULTS_DIR / f"{self.source}.json"
        out.write_text(json.dumps(self.record, indent=2, default=str))
        print(f"[{self.source}] {self.record['status'].upper()} -> {out.relative_to(REPO)}")
        return 0 if exc is None else 1


def run(source: str, body) -> None:
    """Run body(probe) and exit with 0/1. Used as each script's entry point."""
    p = Probe(source)
    try:
        body(p)
    except BaseException as exc:  # noqa: BLE001 - we record and re-exit
        sys.exit(p.finish(exc))
    sys.exit(p.finish())
