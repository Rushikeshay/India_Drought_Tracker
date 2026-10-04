"""Daily refresh: download what changed, rebuild the site's data files, check them.

Steps, in order:
  rain_official  IMD's district rainfall table -> data/processed/imd_official/ (archive; IMD overwrites it daily)
  rain           IMD gridded daily rain for this year -> district daily, weekly, web/data/rain.json
  groundwater    NWDP manual + current-period telemetry -> cycles, pairs, web/data/groundwater.json, gw_history.json
  idm            new weekly drought-index grids -> web/data/idm.json
  classify       web/data/status.json
  history        web/data/history/
  check          pipeline.validate.publish

A failing source step is logged and the run carries on: that layer keeps its previous
files (each layer shows its own date on the site) and the other layers still update.
Nothing is ever filled in for a source that failed. The run exits 1 if any step failed.
web/data may be published only if `classify` and `check` passed (publish=true in
$GITHUB_OUTPUT and in web/data/run.json).

IN-GRES stress is not part of the daily run (yearly edition; run pipeline.process.stress
and stress_history by hand when a new edition appears).

Usage: python -m pipeline.run [--only rain_official,rain] [--skip history]
"""

from __future__ import annotations

import argparse
import logging
import os
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from pipeline import webjson

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web" / "data"
log = logging.getLogger("run")


def rain_official() -> None:
    from pipeline.process import rain_official as m
    m.main([])


def rain() -> None:
    from pipeline.process import rain_current, rain_weekly
    rain_current.update_daily(datetime.now(rain_current.IST).year, True)
    rain_weekly.build()  # dry spells in the metrics below need this year's weeks
    rain_current.main(["--no-download"])


def groundwater() -> None:
    from pipeline.process import groundwater as m
    from pipeline.sources import nwdp
    nwdp.main(["--daily"])
    # no earlier-period telemetry on disk (clean checkout): build on the stored cycles
    history_on_disk = any(not nwdp.CURRENT.search(p.name) for p in (m.RAW / "telemetry").glob("*.csv"))
    m.main(["all"] + ([] if history_on_disk else ["--incremental"]))


def idm() -> None:
    from pipeline.process import idm as m
    m.main([])


def classify() -> None:
    from pipeline.process import classify as m
    m.main()


def history() -> None:
    from pipeline.process import history as m
    m.main([])


def check() -> None:
    from pipeline.validate import publish
    p = publish.problems()
    if p:
        raise RuntimeError("publish check failed: " + "; ".join(p))


STEPS = [rain_official, rain, groundwater, idm, classify, history, check]
MUST_PASS = {"classify", "check"}  # without these the site keeps its previous data


def main(argv=None) -> int:
    names = [f.__name__ for f in STEPS]
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated steps to run: " + ", ".join(names))
    ap.add_argument("--skip", default="", help="comma-separated steps to leave out")
    a = ap.parse_args(argv)
    only, skip = set(filter(None, a.only.split(","))), set(filter(None, a.skip.split(",")))
    unknown = (only | skip) - set(names)
    if unknown:
        ap.error(f"unknown steps: {sorted(unknown)}")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    report = {}
    for f in STEPS:
        name = f.__name__
        if (only and name not in only) or name in skip:
            continue
        t0 = time.time()
        try:
            f()
            report[name] = {"ok": True}
        except (Exception, SystemExit) as exc:  # a module's SystemExit must not end the whole run
            log.error("step %s failed: %s\n%s", name, exc, traceback.format_exc())
            report[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
        report[name]["seconds"] = round(time.time() - t0)
        log.info("step %s: %s in %ds", name, "ok" if report[name]["ok"] else "FAILED", report[name]["seconds"])

    failed = [k for k, v in report.items() if not v["ok"]]
    publish = MUST_PASS <= set(report) and not (MUST_PASS & set(failed))
    if MUST_PASS <= set(report):  # a full run: leave a record next to the data it produced
        (WEB / "run.json").write_text(webjson.dumps(
            {"run_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), "publish": publish, "steps": report}, indent=1))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            fh.write(f"publish={'true' if publish else 'false'}\nfailed={','.join(failed)}\n")
    log.info("run finished: %s; publish=%s", "all steps ok" if not failed else "FAILED: " + ", ".join(failed), publish)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
