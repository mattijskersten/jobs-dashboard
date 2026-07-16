#!/usr/bin/env bash
# Promote a needs-review job to shortlisted (or reject / close / decline it).
#   scripts/promote.sh <job_id>           → shortlisted; next run tailors it
#   scripts/promote.sh <job_id> reject    → rejected (bad fit)
#   scripts/promote.sh <job_id> close     → closed (posting retired before applying)
#   scripts/promote.sh <job_id> decline   → declined (company turned the application down)
# The allowed transitions are defined canonically in the dashboard's
# db.py ACTIONS table (dashboard/src/jobs_dashboard/db.py); the WHERE guards
# below mirror its rules — keep them in sync.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="$ROOT/data/jobs.db"
JOB_ID="${1:?usage: promote.sh <job_id> [reject|close|decline]}"
# Each arm sets both halves of the rule — a verb's target status and the
# statuses it's allowed from — so they can't drift apart. Mirrors db.py ACTIONS.
case "${2:-}" in
  "")      NEW_STATUS="shortlisted"; FROM="('needs-review')" ;;
  reject)  NEW_STATUS="rejected"; FROM="('needs-review','shortlisted','seen')" ;;
  close)   NEW_STATUS="closed"; FROM="('needs-review','shortlisted','tailored')" ;;
  decline) NEW_STATUS="declined"; FROM="('applied')" ;;
  *)       echo "ERROR: unknown verb '${2}' (expected: reject|close|decline)" >&2; exit 1 ;;
esac

CHANGED=$(sqlite3 "$DB" "UPDATE jobs SET status = '$NEW_STATUS', updated_at = datetime('now')
  WHERE job_id = '$JOB_ID' AND status IN $FROM;
  SELECT changes();")
if [ "$CHANGED" = "0" ]; then
  echo "ERROR: $JOB_ID not found in a status that allows → $NEW_STATUS (needs $FROM)" >&2
  sqlite3 -line "$DB" "SELECT job_id, company, title, status FROM jobs WHERE job_id = '$JOB_ID';" >&2
  exit 1
fi
sqlite3 -line "$DB" "SELECT job_id, company, title, score, status FROM jobs WHERE job_id = '$JOB_ID';"
