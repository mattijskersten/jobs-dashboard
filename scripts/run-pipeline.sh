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
DB="$ROOT/data/jobs.db"
LOCK="$ROOT/data/.pipeline.lock"
mkdir -p "$ROOT/data"

exec 9>"$LOCK"
if ! flock -n 9; then
  echo "another pipeline run holds $LOCK — exiting" >&2
  exit 0
fi

"$ROOT/scripts/init-db.sh" >/dev/null

# Collect hiring.cafe before processing. LinkedIn and manual JDs are collected
# on-demand via their own commands, never here. Full window on an empty DB;
# override the window with JOBS_INGEST_DAYS. Ingest failure is tolerated — the
# pipeline still triages/tailors whatever landed and reports. The ingest output
# is logged so /pipeline can surface collection errors in the digest.
DAYS="${JOBS_INGEST_DAYS:-7}"
if [ "$(sqlite3 "$DB" 'SELECT count(*) FROM jobs;' 2>/dev/null || echo 0)" -eq 0 ]; then
  DAYS=121
fi
INGEST_LOG="$ROOT/data/reports/.last-ingest.log"
set +e
"$ROOT/scripts/ingest.sh" --days "$DAYS" >"$INGEST_LOG" 2>&1
echo "INGEST_EXIT=$?" >>"$INGEST_LOG"
set -e
cat "$INGEST_LOG"

cd "$ROOT"
claude -p "/pipeline${*:+ $*}" --output-format text
