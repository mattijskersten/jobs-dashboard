---
description: Full job pipeline run — search hiring.cafe, triage, tailor CVs, write digest
---

Run one full pipeline pass: **search → triage → tailor → report**. You run
unattended — never ask questions; on any unrecoverable error, record it and
still produce the digest. All state lives in `data/jobs.db`; make every state
change with a targeted `sqlite3` `INSERT`/`UPDATE` (never rewrite tables), and
wrap multi-statement changes in a transaction.

## 0. Start the run

- `scripts/init-db.sh` (idempotent).
- Open a run row and remember its id:
  `sqlite3 data/jobs.db "INSERT INTO runs DEFAULT VALUES; SELECT last_insert_rowid();"`
- Read `data/search-profile.md` — it defines the hard filters, soft
  preferences, scoring guide, and search hints. It is the source of truth for
  triage decisions.

## 1. Search (mechanical ingestion)

Run: `scripts/ingest.sh --days 7 --run-id <run_id>`

It executes the eight standard passes from the profile's search hints
(2 tracks × {departments, broad query} × {local-50mi, remote}), paginates
to exhaustion, dedupes against the database, and inserts every unseen hit
as a `status = 'seen'` row with its compact summary in `summary_json` —
deterministically, so no result can be lost in model context. Do **not**
run your own `search_jobs` calls for collection.

Use `--days 121` (the site's full window) when the database is empty, the
last finished run is more than a week old, or the run was invoked with a
backfill instruction.

This step searches **hiring.cafe only**. LinkedIn is collected on-demand via
`/ingest-linkedin` (browser-scraped — kept deliberate), never from here. Any
LinkedIn `seen` rows already in the queue are still triaged in step 2.

Capture its stdout for the digest. Exit code 2 means partial ingest (some
passes failed) — continue with what was inserted and report the errors in
the digest. If it inserted nothing and reported errors, skip to step 3
(a promoted needs-review job may still need tailoring), then write the
digest with the error prominent, finalize the run row, and exit cleanly.

## 2. Triage

Triage operates **only on database rows**, never on remembered search
results. Fetch the queue (it includes any leftovers from a crashed earlier
run, not just this run's inserts):

```
sqlite3 -json data/jobs.db "SELECT job_id, company, title, track, posted_date, summary_json FROM jobs WHERE status = 'seen';"
```

Rows carry a `summary_json.source` that decides which details tool to use:

- `source == "manual"` — a hand-supplied JD (landed by `scripts/ingest-jd.sh`):
  its full description is already on disk at `jd_path` and it has **no**
  hiring.cafe id. Score it from that file, never call any `get_job_details`, and
  skip step 3's fetch/save (already saved).
- `source == "linkedin"` — landed by `/ingest-linkedin`, summary-only, with a
  numeric `summary_json.linkedin_id` and **no** hiring.cafe id. When details are
  needed (step 2/3), call `mcp__linkedin__get_job_details(linkedin_id)` —
  **never** the hiring.cafe one. Be conservative: fetch LinkedIn details
  **sequentially** (no parallel calls) and **cap at 8 per run**. If a ≥6 keeper
  is past the cap, leave it `needs-review` with summary-only and note in the
  digest that its JD fetch was deferred (a later `/promote` or run will fetch it).
- otherwise (hiring.cafe) — use `mcp__hiring-cafe__get_job_details`.

For each `seen` row, judge from its `summary_json` (location,
workplace_type, seniority, role_type, salary, requirements_summary…):

1. **Hard filters are pass/fail** (location, seniority, track fit — see
   profile). A miss is `rejected` with score 1 and a one-line rationale naming
   the failed filter. Do not fetch details for these. Correct `track` if the
   ingest's pass-based guess is wrong.
2. For jobs that pass, score 1–10 against the profile's soft preferences and
   scoring guide (domain, scope, people management, posting freshness — stale
   postings score lower per the profile). Call `get_job_details` when the
   summary leaves a likely-≥6 job ambiguous.
3. **For every job scoring ≥ 6:** fetch full details (if not already), and save
   the complete description as plain text to
   `data/jds/JD $COMPANY $JOBID.txt` (company name stripped of `/\:*?"<>|`).
   Tailoring and later fine-tuning read the JD from disk — never re-fetch it.
4. Update each row (batch ~20 per transaction; double any `'` in strings):
   - score ≥ 8 → `status = 'shortlisted'`
   - 6–7 → `status = 'needs-review'`
   - ≤ 5 → `status = 'rejected'`
   - set score, rationale, jd_path (≥6 only), updated_at.

Before moving on, assert the queue is drained —
`sqlite3 data/jobs.db "SELECT count(*) FROM jobs WHERE status = 'seen';"`
must return 0. If not, triage the stragglers; never leave `seen` rows
behind silently.

## 3. Tailor

Run: `scripts/tailor-pending.sh 5`

It picks every `shortlisted` job — auto-shortlisted just now or promoted from
needs-review earlier — capped at the 5 highest-scoring, and tailors each in
its own headless `claude` session in parallel, storing CV paths and the
session id in the row. Capture its stdout/stderr for the digest. Jobs over the
cap stay `shortlisted` for the next run; failed jobs also stay `shortlisted`
and are reported as errors.

## 4. Report

Write a digest to `data/reports/run-<run_id>-<YYYY-MM-DD>.md`. It replaces
interactive presentation — it must stand alone for someone who didn't watch
the run. Include:

- Run id, date, search windows used.
- **New jobs seen** (count) and a table of every new job: company, title,
  track, posted date, score, status, one-line rationale. Rejects included.
- **Tailored this run:** company, title, posted date, score, CV PDF path,
  the apply link (company portal), and the resume command:
  `claude --resume <session_id>`.
- **Awaiting review** (all `needs-review` rows, not just new ones): company,
  title, posted date, score, rationale, the apply link, and the promote
  command: `scripts/promote.sh <job_id>`.
- **Still queued:** shortlisted jobs beyond this run's tailoring cap.
- **Errors:** every search/details/tailoring failure, or "none".

Finalize the run row (single UPDATE): finished_at, jobs_seen, shortlisted,
needs_review, rejected (new jobs this run), tailored (successes this run),
errors (NULL if none), report_path.

Finally, print the digest verbatim as your last output.
