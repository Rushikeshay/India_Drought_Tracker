#!/usr/bin/env bash
# Scheduled on the Oracle VM by cron (see setup.sh). Pulls new WRIS groundwater
# readings and pushes the updated data/wris/ files to GitHub.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$DIR"
exec 9>/tmp/run_wris.lock
flock -n 9 || { echo "$(date -Is) already running"; exit 0; }

echo "== $(date -Is) start"
git pull -q --rebase
# Commit results/wris.json from the Oracle probe too, if it was re-run.
status=0
.venv/bin/python -m pipeline.sources.wris "$@" || status=$?

git add data/wris data/reference/wris_districts.csv notebooks/phase0/results/oracle 2>/dev/null || true
if ! git diff --cached --quiet; then
  git commit -q -m "WRIS groundwater update $(date +%F) (exit $status)"
  git pull -q --rebase && git push -q
  echo "pushed"
else
  echo "no changes"
fi
# Keep 4 weeks of raw pulls on disk.
find data/raw/wris -mindepth 1 -maxdepth 1 -type d -mtime +28 -exec rm -rf {} + 2>/dev/null || true
echo "== $(date -Is) end (exit $status)"
exit $status
