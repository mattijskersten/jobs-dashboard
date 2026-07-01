#!/usr/bin/env bash
# Tailor the CV for one shortlisted job in its own headless `claude` session.
#
#   scripts/tailor-job.sh <job_id>
#
# Reads company + JD path from data/jobs.db, runs a fresh `claude -p` session
# that writes "data/cvs/cv <Candidate> $COMPANY.md" + PDF (the candidate name is
# read from data/cv.md's front matter), then stores the session id and CV paths
# back in the job's row (status → tailored).
# The stored session id can be resumed later: claude --resume <session_id>
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="$ROOT/data/jobs.db"
JOB_ID="${1:?usage: tailor-job.sh <job_id>}"

row=$(sqlite3 -separator $'\t' "$DB" \
  "SELECT company, title, jd_path FROM jobs WHERE job_id = '$JOB_ID' AND status = 'shortlisted';")
if [ -z "$row" ]; then
  echo "ERROR: job $JOB_ID not found or not shortlisted" >&2
  exit 1
fi
COMPANY=$(printf '%s' "$row" | cut -f1)
TITLE=$(printf '%s' "$row" | cut -f2)
JD_PATH=$(printf '%s' "$row" | cut -f3)
if [ ! -f "$ROOT/$JD_PATH" ]; then
  echo "ERROR: JD file missing for $JOB_ID: $JD_PATH" >&2
  exit 1
fi

# Candidate name from data/cv.md front matter (for the output filename); blank if absent
CANDIDATE=$(sed -n 's/^name:[[:space:]]*//p' "$ROOT/data/cv.md" 2>/dev/null | head -1 | tr -d '"' | sed 's/  */ /g; s/^ //; s/ $//')

# Company name as a filename label (shared rule: scripts/sanitize.py)
LABEL=$(python3 "$ROOT/scripts/sanitize.py" "$COMPANY")
if [ -n "$CANDIDATE" ]; then BASE="cv $CANDIDATE $LABEL"; else BASE="cv $LABEL"; fi
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

PROMPT="Tailor the CV in data/cv.md for one job application. Work strictly by the rules in tooling/AGENTS.md (read it first).

Job: $TITLE at $COMPANY
Job description: read it from \"$JD_PATH\" (do not search for the posting online; the file is the source of truth).

Steps:
1. Read tooling/AGENTS.md, then the JD, then data/cv.md, then these worked example CVs as style references: $REF_LIST. Read only those as references.
2. Before drafting anything, write out the 3-5 most important themes from the JD — its top requirements, the seniority/scope signals (org size, revenue, stage), the domain emphasis, and the terminology it repeats (to mirror where truthful). This is the brief; every choice in the next step must serve it.
3. Write the tailored CV to \"$CV_MD\" following the conventions and tailoring scope in tooling/AGENTS.md exactly, leading with the themes from step 2 (most relevant content first).
4. Build the PDF: tooling/build.sh \"$CV_MD\" \"$CV_PDF\"
5. Check page count with pdfinfo; target 2 pages, tighten and rebuild if 3.
6. Finish with a short report: the themes you committed to in step 2 and the main changes you made to serve them and why."

cd "$ROOT"
set +e
OUT=$(claude -p "$PROMPT" --output-format json 2>"$ROOT/data/reports/.tailor-$JOB_ID.err")
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
