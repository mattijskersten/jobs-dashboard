---
description: Promote a needs-review job to shortlisted (or reject it) — next run tailors it
argument-hint: <job_id | company name> [reject]
---

Promote or reject a job that triage put in `needs-review`: $ARGUMENTS

1. If the argument looks like a company name rather than a job id, find it:
   `sqlite3 -line data/jobs.db "SELECT job_id, company, title, score, rationale FROM jobs WHERE status = 'needs-review' AND company LIKE '%…%';"`
   If nothing or several rows match, show the full needs-review list and stop.
2. Run `scripts/promote.sh <job_id>` (append `reject` if the user asked to
   reject). It only touches rows currently in `needs-review`.
3. Confirm the result to the user. A promoted job is picked up by the next
   pipeline run like any other shortlisted job; to tailor it immediately, run
   `scripts/tailor-pending.sh` — mention this option.

Promoting never needs a JD fetch of its own: a job whose JD was never fetched
(triage only fetches at score ≥ 6, and LinkedIn fetches are capped per run)
has it fetched at tailor time by `scripts/ensure-jd.sh`, which `tailor-job.sh`
calls. The same holds for jobs promoted with the dashboard's button.
