#!/usr/bin/env bash
# Make sure one job's JD is on disk, fetching it if it is not.
#
#   scripts/ensure-jd.sh <job_id>
#
# Triage only fetches JDs for jobs it scores >= 6, and LinkedIn fetches are
# additionally capped per run — so a needs-review row promoted later (from the
# dashboard, or scripts/promote.sh) reaches tailoring with no jd_path and
# tailor-job.sh fails on the missing file. This script is the self-heal: it is
# called at tailor time, so every path into 'shortlisted' is covered by one
# implementation and no scrape is spent on a job that never gets tailored.
#
# Idempotent: a job whose JD is already on disk is a no-op.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="$ROOT/data/jobs.db"
JOB_ID="${1:?usage: ensure-jd.sh <job_id>}"

row=$(sqlite3 -separator $'\t' "$DB" \
  "SELECT COALESCE(jd_path, ''), company,
          COALESCE(json_extract(summary_json, '\$.source'), 'hiring-cafe')
   FROM jobs WHERE job_id = '$JOB_ID';")
if [ -z "$row" ]; then
  echo "ERROR: no jobs row for $JOB_ID" >&2
  exit 1
fi
JD_PATH=$(printf '%s' "$row" | cut -f1)
COMPANY=$(printf '%s' "$row" | cut -f2)
SOURCE=$(printf '%s' "$row" | cut -f3)

if [ -n "$JD_PATH" ] && [ -f "$ROOT/$JD_PATH" ]; then
  exit 0
fi

case "$SOURCE" in
  manual)
    # ingest-jd.sh writes the file and sets jd_path at landing time, so a manual
    # row without one is a defect upstream — there is nothing to re-fetch from.
    echo "ERROR: manual job $JOB_ID has no JD on disk (jd_path='$JD_PATH') — re-land it with scripts/ingest-jd.sh" >&2
    exit 1
    ;;
  linkedin)
    # LinkedIn has no in-repo client: its JD is only reachable through the MCP's
    # logged-in browser session, i.e. from inside a claude session. Keep the
    # session's job purely mechanical — fetch, pipe verbatim to save-jd.py,
    # which owns the write and the jd_path update.
    LI_ID=$(sqlite3 "$DB" "SELECT json_extract(summary_json, '\$.linkedin_id') FROM jobs WHERE job_id = '$JOB_ID';")
    if [ -z "$LI_ID" ] || [ "$LI_ID" = "null" ]; then
      echo "ERROR: $JOB_ID has source=linkedin but no summary_json.linkedin_id" >&2
      exit 1
    fi
    P_COMPANY=$(printf '%s' "$COMPANY" | tr -d '"\\')
    PROMPT="Fetch one LinkedIn job description and save it to disk. Do exactly this, nothing else:

1. Call mcp__linkedin__get_job_details with job_id \"$LI_ID\".
2. Pipe the posting's description text verbatim to:
   scripts/save-jd.py --job-id \"$JOB_ID\" --company \"$P_COMPANY\"
   Write it exactly as returned — do not summarize, reformat, re-order, or add headers.
   Skip LinkedIn's own page furniture (nav, 'people you can reach out to',
   premium insights, similar-jobs blocks); the job posting text itself is the JD.

If the tool returns no description (some 'Promoted by hirer' postings omit the
body), say so and stop — do not invent or reconstruct the text."

    cd "$ROOT"
    set +e
    claude -p "$PROMPT" --model opus --effort medium \
      --allowedTools "mcp__linkedin__get_job_details" "Bash(scripts/save-jd.py:*)" \
      --output-format text >"$ROOT/data/reports/.ensure-jd-$JOB_ID.log" 2>&1
    RC=$?
    set -e
    ;;
  *)
    set +e
    "$ROOT/scripts/fetch-jd.sh" "$JOB_ID" --company "$COMPANY" >/dev/null
    RC=$?
    set -e
    ;;
esac

# Trust the database, not the exit code: the fetch counts only if save-jd.py /
# fetch-jd.py actually set jd_path and the file landed.
JD_PATH=$(sqlite3 "$DB" "SELECT COALESCE(jd_path, '') FROM jobs WHERE job_id = '$JOB_ID';")
if [ -z "$JD_PATH" ] || [ ! -f "$ROOT/$JD_PATH" ]; then
  echo "ERROR: could not fetch a JD for $JOB_ID (source=$SOURCE, rc=${RC:-?})" >&2
  if [ "$SOURCE" = "linkedin" ]; then
    echo "  see data/reports/.ensure-jd-$JOB_ID.log" >&2
  fi
  exit 1
fi
if [ "$SOURCE" = "linkedin" ]; then
  rm -f "$ROOT/data/reports/.ensure-jd-$JOB_ID.log"
fi
echo "fetched JD for $JOB_ID ($SOURCE): $JD_PATH"
