#!/usr/bin/env bash
# Headless entry point for the full pipeline: search → triage → tailor → report.
# Takes an exclusive lockfile so overlapping runs (e.g. a slow nightly run still
# going when the next fires) exit cleanly instead of racing on the database.
#
# Extra arguments are passed to the pipeline as instructions, e.g.:
#   scripts/run-pipeline.sh "backfill: use posted_within_days 121 for all passes"
#
# Cron usage: see README.md.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCK="$ROOT/data/.pipeline.lock"
mkdir -p "$ROOT/data"

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "another pipeline run holds $LOCK — exiting" >&2
  exit 0
fi

"$ROOT/scripts/init-db.sh" >/dev/null
cd "$ROOT"
claude -p "/pipeline${*:+ $*}" --output-format text
