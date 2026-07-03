#!/usr/bin/env bash
# Tailor the CV for one shortlisted job in its own headless `claude` session.
#
#   scripts/tailor-job.sh <job_id>
#
# Reads company + JD path from data/jobs.db, runs a fresh `claude -p` session
# that writes "data/cvs/cv <Candidate> $COMPANY.md" + PDF (the candidate name is
# read from data/cv.md's front matter; the job title is appended when the
# company has other CV-bearing jobs), then stores the session id and CV paths
# back in the job's row (status → tailored).
# The stored session id can be resumed later: claude --resume <session_id>
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="$ROOT/data/jobs.db"
JOB_ID="${1:?usage: tailor-job.sh <job_id>}"

row=$(sqlite3 -separator $'\t' "$DB" \
  "SELECT company, title, jd_path, COALESCE(score, ''), COALESCE(rationale, '')
   FROM jobs WHERE job_id = '$JOB_ID' AND status = 'shortlisted';")
if [ -z "$row" ]; then
  echo "ERROR: job $JOB_ID not found or not shortlisted" >&2
  exit 1
fi
COMPANY=$(printf '%s' "$row" | cut -f1)
TITLE=$(printf '%s' "$row" | cut -f2)
JD_PATH=$(printf '%s' "$row" | cut -f3)
SCORE=$(printf '%s' "$row" | cut -f4)
RATIONALE=$(printf '%s' "$row" | cut -f5-)
if [ ! -f "$ROOT/$JD_PATH" ]; then
  echo "ERROR: JD file missing for $JOB_ID: $JD_PATH" >&2
  exit 1
fi

# Candidate name from data/cv.md front matter (for the output filename); blank if absent
CANDIDATE=$(sed -n 's/^name:[[:space:]]*//p' "$ROOT/data/cv.md" 2>/dev/null | head -1 | tr -d '"' | sed 's/  */ /g; s/^ //; s/ $//')

# Company name as a filename label (shared rule: scripts/sanitize.py)
LABEL=$(python3 "$ROOT/scripts/sanitize.py" "$COMPANY")
if [ -n "$CANDIDATE" ]; then BASE="cv $CANDIDATE $LABEL"; else BASE="cv $LABEL"; fi

# One company can have several live roles (e.g. two openings at one company); a
# company-only filename would make them clobber each other's CV. When another
# CV-bearing job at the same company exists, append the job title — the file
# name stays human-readable for uploading straight into application forms.
# If even the title matches another live role, fall back to the job id.
ESC_COMPANY=$(printf '%s' "$COMPANY" | sed "s/'/''/g")
ESC_TITLE=$(printf '%s' "$TITLE" | sed "s/'/''/g")
DUP=$(sqlite3 "$DB" "SELECT count(*) FROM jobs
  WHERE company = '$ESC_COMPANY' AND job_id != '$JOB_ID'
    AND status IN ('shortlisted', 'tailored', 'applied');")
if [ "$DUP" -gt 0 ]; then
  BASE="$BASE $(python3 "$ROOT/scripts/sanitize.py" "$TITLE")"
  SAME_TITLE=$(sqlite3 "$DB" "SELECT count(*) FROM jobs
    WHERE company = '$ESC_COMPANY' AND title = '$ESC_TITLE' AND job_id != '$JOB_ID'
      AND status IN ('shortlisted', 'tailored', 'applied');")
  [ "$SAME_TITLE" -gt 0 ] && BASE="$BASE $JOB_ID"
fi
CV_MD="data/cvs/$BASE.md"
CV_PDF="data/cvs/$BASE.pdf"

# Worked-example CVs to feed the model as style references. Prefer your real
# ones in data/references/ (gitignored); fall back to the shipped sanitized
# templates/cv-example-*.md only when no real reference is present (fresh clone).
refs=()
for f in "$ROOT"/data/references/*.md; do
  [ -e "$f" ] && refs+=("data/references/$(basename "$f")")
done
if [ "${#refs[@]}" -eq 0 ]; then
  for f in "$ROOT"/templates/cv-example-*.md; do
    [ -e "$f" ] && refs+=("templates/$(basename "$f")")
  done
fi
REF_LIST=""
for r in ${refs[@]+"${refs[@]}"}; do REF_LIST+="\"$r\", "; done
REF_LIST="${REF_LIST%, }"
[ -z "$REF_LIST" ] && REF_LIST="(no worked examples available)"

# Title/company are echoed inside the prompt near quoted paths — strip
# characters that would garble that quoting (filenames use LABEL, not these).
P_TITLE=$(printf '%s' "$TITLE" | tr -d '"\\')
P_COMPANY=$(printf '%s' "$COMPANY" | tr -d '"\\')
if [ -n "$SCORE" ] || [ -n "$RATIONALE" ]; then
  TRIAGE_LINE="Triage shortlisted it${SCORE:+ scoring $SCORE/10}${RATIONALE:+: $RATIONALE}"
else
  TRIAGE_LINE="(no triage score/rationale recorded)"
fi

PROMPT="Tailor the CV in data/cv.md for one job application.

Job: $P_TITLE at $P_COMPANY
$TRIAGE_LINE
Job description: read it from \"$JD_PATH\" (do not search for the posting online; the file is the source of truth).

Read tooling/AGENTS.md first and follow its Tailoring workflow — all 7 steps, including the keyword-coverage check and the rendered-PDF skim. Per-job specifics:
- Style-reference CVs for step 1: $REF_LIST. Read only those as references.
- Write the tailored CV to \"$CV_MD\".
- Build the PDF with: tooling/build.sh \"$CV_MD\" \"$CV_PDF\". If it runs over 2 pages, tighten and rebuild until it fits.
- Before the final report, confirm every claim in the tailored CV traces back to data/cv.md or a reference CV; fix anything that doesn't."

cd "$ROOT"
set +e
# CV writing is pinned to fable, the strongest model — tailoring quality is
# what lands interviews. Triage runs on opus (see run-pipeline.sh).
OUT=$(claude -p "$PROMPT" --model fable --output-format json 2>"$ROOT/data/reports/.tailor-$JOB_ID.err")
RC=$?
set -e

SESSION_ID=$(printf '%s' "$OUT" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("session_id",""))
except Exception: print("")')
IS_ERROR=$(printf '%s' "$OUT" | python3 -c 'import json,sys
try: print("1" if json.load(sys.stdin).get("is_error") else "0")
except Exception: print("1")')

if [ "$RC" -ne 0 ] || [ "$IS_ERROR" != "0" ] || [ ! -f "$ROOT/$CV_MD" ] || [ ! -f "$ROOT/$CV_PDF" ]; then
  echo "ERROR: tailoring failed for $JOB_ID ($COMPANY) — rc=$RC, see data/reports/.tailor-$JOB_ID.err" >&2
  [ -n "$SESSION_ID" ] && sqlite3 "$DB" \
    "UPDATE jobs SET tailoring_session_id = '$SESSION_ID', updated_at = datetime('now') WHERE job_id = '$JOB_ID';"
  exit 1
fi

sqlite3 "$DB" "UPDATE jobs SET
    status = 'tailored',
    cv_md_path = '$(printf '%s' "$CV_MD" | sed "s/'/''/g")',
    cv_pdf_path = '$(printf '%s' "$CV_PDF" | sed "s/'/''/g")',
    tailoring_session_id = '$SESSION_ID',
    updated_at = datetime('now')
  WHERE job_id = '$JOB_ID';"
rm -f "$ROOT/data/reports/.tailor-$JOB_ID.err"
echo "tailored $JOB_ID ($COMPANY) session=$SESSION_ID cv=$CV_PDF"
