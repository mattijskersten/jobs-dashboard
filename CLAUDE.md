# CLAUDE.md

CV-driven job search agent: collect jobs (hiring.cafe / LinkedIn / manual JD)
→ triage against `data/search-profile.md` → tailor CVs in headless sessions →
digest. All state lives in `data/jobs.db` (SQLite); the model does judgment
(triage, tailoring), deterministic scripts do everything mechanical.

## Where things are documented

- `README.md` — layout, setup, how a run works, job statuses, dashboard.
- `docs/status-lifecycle.md` — the status state machine. Canonical definitions
  live in `dashboard/src/jobs_dashboard/db.py` (`STATUS_ORDER` + `ACTIONS`) and
  the `CHECK` constraint in `scripts/schema.sql`; the doc mirrors them.
- `tooling/TRIAGE.md` — how a job is scored; `tooling/AGENTS.md` — CV
  tailoring rules and build workflow.
- `scripts/README.md` — which scripts are entry points and which are helpers.

## Hard rules

- **Nothing runs on a schedule.** Ingest and pipeline are manual-only
  (`/ingest-*`, `/pipeline`, or `scripts/run-pipeline.sh`). The README's cron
  section describes an optional setup that is not enabled: an old error in
  `data/reports/.last-ingest.log` is a leftover from a past manual run, not a
  live failure.
- **Pace hiring.cafe bulk calls.** `sleep 1` before every job-details fetch
  inside a loop. A 403 (Vercel checkpoint) is an intermittent IP-level
  cooldown — wait it out; there is no challenge cookie to solve and no
  workaround to hunt for.
- **LinkedIn is browser-scraped — use it conservatively.** On-demand only via
  `/ingest-linkedin`, sequential and paced, never scheduled or bulk. Its MCP
  caps results at ~10 per call, so prefer more, narrower search passes over
  broadening one filter. "Promoted by hirer" postings return no body from
  `get_job_details` — land those manually via `scripts/save-jd.py`.
- **Tailoring claims** follow `tooling/AGENTS.md`. Never merge facts from
  separate roles into one CV claim, and read `data/tailoring-notes.md`
  (gitignored, if present) for candidate-specific claim-scope corrections.
- **Git**: solo repo — commit and push directly to `main`; don't create
  branches by default.
- **Everything under `data/` is personal and gitignored.** Never commit it and
  never copy its contents into committed files.
