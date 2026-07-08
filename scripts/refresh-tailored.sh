#!/usr/bin/env bash
# Refresh already-tailored CVs with facts added to data/cv.md after their
# tailoring runs — by resuming each job's original tailoring session
# (tailoring_session_id, stored by tailor-job.sh) with a template prompt.
# The resumed session already holds the JD, references, and its own tailoring
# rationale; the prompt carries only the delta and forces a re-read of the
# files on disk (cv.md and the tailored CV may have changed since).
# Sessions run sequentially, one at a time (see tailor-pending.sh).
#
#   scripts/refresh-tailored.sh              # all jobs in status 'tailored'
#   scripts/refresh-tailored.sh id1 id2 ...  # only these job ids
#
# The additions under review live in scripts/refresh-additions.md — edit that
# file per refresh campaign. Sessions make additive-only edits: existing CV
# content (which may be hand-edited) is never rephrased or cut.
# Each session's structured report is appended to data/reports/refresh-<date>.md.
# Job status and cv paths are not changed; failures don't abort the batch.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="$ROOT/data/jobs.db"
ADDITIONS="scripts/refresh-additions.md"
if [ ! -f "$ROOT/$ADDITIONS" ]; then
  echo "ERROR: $ADDITIONS not found — write the campaign's additions first" >&2
  exit 1
fi

if [ "$#" -gt 0 ]; then
  IDS=("$@")
else
  mapfile -t IDS < <(sqlite3 "$DB" \
    "SELECT job_id FROM jobs WHERE status = 'tailored'
       AND cv_md_path IS NOT NULL AND cv_md_path != ''
     ORDER BY score DESC, date_seen ASC;")
fi
if [ "${#IDS[@]}" -eq 0 ]; then
  echo "nothing to refresh"
  exit 0
fi

REPORT="$ROOT/data/reports/refresh-$(date +%Y%m%d).md"
mkdir -p "$ROOT/data/reports"
echo "refreshing ${#IDS[@]} job(s): ${IDS[*]}"
echo "report: $REPORT"

fail=0
for id in "${IDS[@]}"; do
  row=$(sqlite3 -separator $'\t' "$DB" \
    "SELECT company, title, cv_md_path, COALESCE(cv_pdf_path, ''), COALESCE(tailoring_session_id, '')
     FROM jobs WHERE job_id = '$id' AND status = 'tailored';")
  if [ -z "$row" ]; then
    echo "SKIP $id: not found or not in status 'tailored'"
    continue
  fi
  COMPANY=$(printf '%s' "$row" | cut -f1)
  TITLE=$(printf '%s' "$row" | cut -f2)
  CV_MD=$(printf '%s' "$row" | cut -f3)
  CV_PDF=$(printf '%s' "$row" | cut -f4)
  SESSION_ID=$(printf '%s' "$row" | cut -f5)
  [ -z "$CV_PDF" ] && CV_PDF="${CV_MD%.md}.pdf"
  if [ -z "$SESSION_ID" ]; then
    echo "SKIP $id ($COMPANY): no tailoring_session_id stored — refresh it manually"
    fail=$((fail + 1))
    continue
  fi
  if [ ! -f "$ROOT/$CV_MD" ]; then
    echo "SKIP $id ($COMPANY): tailored CV missing: $CV_MD"
    fail=$((fail + 1))
    continue
  fi

  # Title/company are echoed inside the prompt near quoted paths — strip
  # characters that would garble that quoting (same rule as tailor-job.sh).
  P_TITLE=$(printf '%s' "$TITLE" | tr -d '"\\')
  P_COMPANY=$(printf '%s' "$COMPANY" | tr -d '"\\')

  PROMPT="Follow-up on the CV you tailored in this session for $P_TITLE at $P_COMPANY.

Since that run, the candidate added new facts to the master data/cv.md, and the tailored CV may have been hand-edited — your memory of both files is stale. Re-read from disk, in this order:
1. \"$ADDITIONS\" — the additions under review, with binding claim-scope limits
2. data/cv.md — the updated fact base; its HTML comments are binding tailoring notes
3. \"$CV_MD\" — the tailored CV as it stands now; treat all existing content as final

The JD you already read is unchanged and remains the source of truth; do not search for it online.

Task: for each addition in \"$ADDITIONS\", decide whether it serves this JD per the keyword-mirroring rules in tooling/AGENTS.md, and put the ones that do where they carry weight (summary / Core Competencies / first bullets of the most relevant role). Rules:
- Additive-only edits: never rephrase, reorder, or delete existing content. If the 2-page limit forces a cut, trim or drop your own additions only. If a valuable addition cannot fit, skip it and flag it.
- Every phrase you add must trace to data/cv.md; the claim-scope limits in \"$ADDITIONS\" override the JD's wording.
- Rebuild with: tooling/build.sh \"$CV_MD\" \"$CV_PDF\" — then confirm the page count is at most 2 via pdfinfo.
- Mechanical checks on the rebuilt PDF, fix and rebuild if found: (a) if the markdown front matter has no github: line the template renders a dangling icon after the LinkedIn link — restore the github: line from data/cv.md; (b) scan the extracted text for mid-word line breaks in compound terms (e.g. \"De-\" + \"vOps\") and wrap the affected word in \\mbox{...} in the markdown; (c) unescaped dollar signs.

Your final message must be exactly this block, nothing after it:
REPORT
added: <semicolon-separated placements, or none>
skipped: <addition — reason; ..., or none>
flags: <anything needing the candidate's attention, or none>
pages: <N>"

  cd "$ROOT"
  set +e
  # Same pinning as tailoring: refresh quality is tailoring quality.
  OUT=$(claude --resume "$SESSION_ID" -p "$PROMPT" --model fable --effort high --output-format json 2>"$ROOT/data/reports/.refresh-$id.err")
  RC=$?
  set -e

  RESULT=$(printf '%s' "$OUT" | python3 -c 'import json,sys
try:
    d = json.load(sys.stdin)
    print("" if d.get("is_error") else d.get("result", ""))
except Exception:
    print("")')
  NEW_SESSION=$(printf '%s' "$OUT" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("session_id",""))
except Exception: print("")')

  if [ "$RC" -ne 0 ] || [ -z "$RESULT" ]; then
    echo "ERROR: refresh failed for $id ($COMPANY) — rc=$RC, see data/reports/.refresh-$id.err" >&2
    fail=$((fail + 1))
    {
      printf '\n## %s — %s (%s)\n\n' "$COMPANY" "$TITLE" "$id"
      printf 'FAILED (rc=%s) — see data/reports/.refresh-%s.err\n' "$RC" "$id"
    } >> "$REPORT"
    continue
  fi

  # Resuming forks a new session id; keep the row pointing at the latest
  # conversation so a future refresh resumes with full history.
  if [ -n "$NEW_SESSION" ]; then
    sqlite3 "$DB" "UPDATE jobs SET tailoring_session_id = '$NEW_SESSION',
      updated_at = datetime('now') WHERE job_id = '$id';"
  fi

  {
    printf '\n## %s — %s (%s)\n\n' "$COMPANY" "$TITLE" "$id"
    printf '%s\n' "$RESULT"
  } >> "$REPORT"
  rm -f "$ROOT/data/reports/.refresh-$id.err"
  echo "refreshed $id ($COMPANY) session=$NEW_SESSION"
done

echo "done: $(( ${#IDS[@]} - fail )) refreshed, $fail failed — review $REPORT"
exit 0
