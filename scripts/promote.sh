#!/usr/bin/env bash
# Promote a needs-review job to shortlisted (or reject it).
#   scripts/promote.sh <job_id>           → shortlisted; next run tailors it
#   scripts/promote.sh <job_id> reject    → rejected
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="$ROOT/data/jobs.db"
JOB_ID="${1:?usage: promote.sh <job_id> [reject]}"
NEW_STATUS="shortlisted"
[ "${2:-}" = "reject" ] && NEW_STATUS="rejected"

CHANGED=$(sqlite3 "$DB" "UPDATE jobs SET status = '$NEW_STATUS', updated_at = datetime('now')
  WHERE job_id = '$JOB_ID' AND status = 'needs-review';
  SELECT changes();")
if [ "$CHANGED" = "0" ]; then
  echo "ERROR: $JOB_ID not found in needs-review" >&2
  sqlite3 -line "$DB" "SELECT job_id, company, title, status FROM jobs WHERE job_id = '$JOB_ID';" >&2
  exit 1
fi
sqlite3 -line "$DB" "SELECT job_id, company, title, score, status FROM jobs WHERE job_id = '$JOB_ID';"
