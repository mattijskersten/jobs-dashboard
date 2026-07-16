---
description: Process the job queue — triage seen jobs, tailor CVs, write digest
---

Run one pipeline pass over whatever is already in the queue: **triage → tailor
→ report**. Collection is a separate step done before this command — hiring.cafe
via `/ingest-hiringcafe` (or the nightly `run-pipeline.sh`), LinkedIn via
`/ingest-linkedin`, manual JDs via `/ingest-jd` — each lands `status = 'seen'`
rows. You only process them; never run searches here. You run unattended — never
ask questions; on any unrecoverable error, record it and still produce the
digest. All state lives in `data/jobs.db`; make every state change with a
targeted `sqlite3` `INSERT`/`UPDATE` (never rewrite tables), and wrap
multi-statement changes in a transaction.

## 0. Start the run

- `scripts/init-db.sh` (idempotent).
- Open a run row and remember its id:
  `sqlite3 data/jobs.db "INSERT INTO runs DEFAULT VALUES; SELECT last_insert_rowid();"`
- **Claim the queue for this run** so the digest can report what is new:
  `sqlite3 data/jobs.db "UPDATE jobs SET first_seen_run_id = <run_id> WHERE status = 'seen' AND first_seen_run_id IS NULL;"`
  (collection commands leave it NULL; this attributes every newly-collected job
  — hiring.cafe, LinkedIn, or manual — to this run).
- Read `tooling/TRIAGE.md` — the scoring procedure — and
  `data/search-profile.md` — the hard filters, soft preferences, and scoring
  guide it applies. Together they are the source of truth for triage.

## 1. Triage

Triage operates **only on database rows**, never on remembered search
results. Fetch the queue (it includes any leftovers from a crashed earlier
run, not just this run's inserts):

```
sqlite3 -json data/jobs.db "SELECT job_id, company, title, track, posted_date, summary_json FROM jobs WHERE status = 'seen';"
```

Rows carry a `summary_json.source` that decides which details tool to use:

- `source == "manual"` — a hand-supplied JD (landed by `scripts/ingest-jd.sh`):
  its full description is already on disk at `jd_path` and it has **no**
  hiring.cafe id. Score it from that file, never fetch, and skip step 3's
  fetch/save (already saved).
- `source == "linkedin"` — landed by `/ingest-linkedin`, summary-only, with a
  numeric `summary_json.linkedin_id` and **no** hiring.cafe id. When details are
  needed (step 2/3), call `mcp__linkedin__get_job_details(linkedin_id)` —
  **never** the hiring.cafe one — then pipe its `description` field **verbatim**
  to `scripts/save-jd.py --job-id <job_id> --company "<name>"` (it writes the raw
  JD and sets `jd_path`; do not reformat or summarize the text yourself). Be
  conservative: fetch LinkedIn details **sequentially** (no parallel calls) and
  **cap at 8 per run**. If a ≥6 keeper is past the cap, leave it `needs-review`
  with summary-only and note in the digest that its JD fetch was deferred (a
  later `/promote` or run will fetch it).
- otherwise (hiring.cafe) — fetch with `scripts/fetch-jd.sh <job_id> --company
  "<name>"` (not the MCP `get_job_details` tool). It writes the raw JD to
  `data/jds/` and sets `jd_path`; score from its structured JSON stdout. The full
  description never enters context — read the saved file only if the prose is
  needed to score.

For each `seen` row, judge from its `summary_json` (location,
workplace_type, seniority, role_type, salary, requirements_summary…) and
score it by the rules in `tooling/TRIAGE.md`. Batch specifics on top of
those rules:

- Fetch the row's details (per the source rules above) when the summary leaves
  a likely-≥6 job ambiguous; hard-filter rejects never get a fetch. The fetch
  tooling saves the raw JD and sets `jd_path` — you never write JD text.
- Every job scoring ≥ 6 must have its JD on disk, so fetch it if you have not
  already; manual rows already have the JD on disk. A fetch always saves, so an
  ambiguous fetch that ends up < 6 harmlessly leaves its JD on disk too.
- Batch the row updates ~20 per transaction (score, rationale, status,
  updated_at — `jd_path` is set by the fetch tooling).

Before moving on, assert the queue is drained —
`sqlite3 data/jobs.db "SELECT count(*) FROM jobs WHERE status = 'seen';"`
must return 0. If not, triage the stragglers; never leave `seen` rows
behind silently.

## 2. Tailor

Run: `scripts/tailor-pending.sh 5`

It picks every `shortlisted` job — auto-shortlisted just now or promoted from
needs-review earlier — capped at the 5 highest-scoring, and tailors each in
its own headless `claude` session, run sequentially (one at a time, so each
session reuses the previous one's prompt cache), storing CV paths and the
session id in the row. Capture its stdout/stderr for the digest. Jobs over the
cap stay `shortlisted` for the next run; failed jobs also stay `shortlisted`
and are reported as errors.

## 3. Report

Write a digest to `data/reports/run-<run_id>-<YYYY-MM-DD>.md`. It replaces
interactive presentation — it must stand alone for someone who didn't watch
the run. Include:

- Run id, date.
- **Collection:** if `data/reports/.last-ingest.log` exists, summarize it (the
  hiring.cafe window and counts) and surface any failed passes or a non-zero
  `INGEST_EXIT` as errors. (Absent when collection was run separately — say so.)
- **New jobs seen** (count = rows with `first_seen_run_id = <run_id>`) and a
  table of every new job: company, title, track, posted date, score, status,
  one-line rationale. Rejects included.
- **Tailored this run:** company, title, posted date, score, CV PDF path,
  the apply link (company portal), and the resume command:
  `claude --resume <session_id>`.
- **Awaiting review** (all `needs-review` rows, not just new ones): company,
  title, posted date, score, rationale, the apply link, and the promote
  command: `scripts/promote.sh <job_id>`.
- **Still queued:** shortlisted jobs beyond this run's tailoring cap.
- **Errors:** every details/tailoring failure, plus any collection error from
  the ingest log, or "none".

Finalize the run row (single UPDATE): finished_at, jobs_seen, shortlisted,
needs_review, rejected (new jobs this run), tailored (successes this run),
errors (NULL if none), report_path.

Finally, print the digest verbatim as your last output.
