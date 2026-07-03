#!/usr/bin/env bash
# Tailor all shortlisted jobs, highest score first, capped at 5 per run,
# in sequential headless `claude` sessions — one at a time, so each session
# after the first reads the shared-prefix prompt cache its predecessor wrote
# (parallel launches all raced past the cache and paid ~5x the writes).
# Prints one line per job; failures are reported but do not abort the batch.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="$ROOT/data/jobs.db"
CAP="${1:-5}"

# Highest score first; among equals, freshest posting first (NULL posted_date
# sorts last under DESC), then oldest in queue.
mapfile -t IDS < <(sqlite3 "$DB" \
  "SELECT job_id FROM jobs WHERE status = 'shortlisted'
   ORDER BY score DESC, posted_date DESC, date_seen ASC LIMIT $CAP;")

if [ "${#IDS[@]}" -eq 0 ]; then
  echo "nothing to tailor"
  exit 0
fi

echo "tailoring ${#IDS[@]} job(s): ${IDS[*]}"
fail=0
for id in "${IDS[@]}"; do
  "$ROOT/scripts/tailor-job.sh" "$id" || fail=$((fail + 1))
done

echo "done: $(( ${#IDS[@]} - fail )) tailored, $fail failed"
exit 0
