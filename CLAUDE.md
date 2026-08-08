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
  `/ingest-linkedin` (job search) and `/warm-intros` (people lookup for one
  job, drafts only — never send), sequential and paced, never scheduled or
  bulk. Its MCP
  caps results at ~10 per call, so prefer more, narrower search passes over
  broadening one filter.
- **`get_job_details` drops the JD body at random — always retry once.** The
  scrape sometimes returns the header, apply chrome and company boilerplate
  with no "About the job" block; an immediate retry on the same id usually
  returns the full text (verified 2026-08-07 on 4 postings, 4/4 recovered).
  It is a race, not a property of "Promoted by hirer" postings — the extractor
  has no hydration wait for `/jobs/view/` pages. Reported upstream as
  [stickerdaniel/linkedin-mcp-server#687](https://github.com/stickerdaniel/linkedin-mcp-server/issues/687);
  drop this rule when it is fixed. Only fall back to landing the JD by hand via
  `scripts/save-jd.py` if a retry also comes back bodyless.
- **Check whether a posting is still live before spending judgment on it.**
  Postings die quietly and a stale `needs-review` row looks identical to a
  fresh one: a sweep on 2026-08-07 found 34 of 90 `needs-review` rows already
  dead, 15 of them scored 7. Liveness is mechanical, so never burn a scrape or
  model reasoning on it:
  - hiring.cafe — `scripts/fetch-jd.sh <id>` prints `No job found` for a
    delisted posting (keep the `sleep 1` pacing).
  - LinkedIn — use the **logged-out guest endpoint**, not `get_job_details`:
    `curl -s https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/<numeric-id>`
    returns HTML containing `No longer accepting applications` when the posting
    is closed. No login, no browser, no bot-flag exposure — so this does *not*
    count against the conservative-use rule above and is the right tool for any
    bulk liveness check. Validated against four postings of known state.
- **Tailoring claims** follow `tooling/AGENTS.md`. Never merge facts from
  separate roles into one CV claim, and read `data/tailoring-notes.md`
  (gitignored, if present) for candidate-specific claim-scope corrections.
- **Git**: solo repo — commit and push directly to `main`; don't create
  branches by default.
- **Everything under `data/` is personal and gitignored.** Never commit it and
  never copy its contents into committed files.
