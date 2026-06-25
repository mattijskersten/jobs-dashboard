# jobs-dashboard

CV-driven job search agent. A nightly pipeline searches
[hiring.cafe](https://hiring.cafe) for senior roles matching the two tracks you
define in `data/search-profile.md`, triages them against that profile, tailors
your CV for the best matches in parallel headless Claude sessions, and writes a
standalone digest. All state lives in a SQLite database designed to back a
future dashboard.

The repo has three top-level content folders: **`tooling/`** (CV build assets +
tailoring rules), **`templates/`** (sanitized `*.example.*` files that ship),
and **`data/`** (all your real, personal content — gitignored wholesale, never
committed). Copy the templates into `data/` to get started (see **Setup**).

## Layout

| Path | Purpose |
|---|---|
| `hiring-cafe-mcp/` | MCP server for the unofficial hiring.cafe API (see its README) |
| `.claude/commands/` | `/pipeline` (triage → tailor → report the queue); the collection commands `/ingest-hiringcafe`, `/ingest-linkedin`, `/ingest-jd`; and `/promote` |
| `tooling/` | CV build assets (`build.sh`, `cv-template.tex`, `cv-filter.lua`) and tailoring rules (`AGENTS.md`) |
| `templates/` | Sanitized templates that ship: `cv.example.md`, `search-profile.example.md`, `cv-example-{1,2}.md` |
| `scripts/` | `run-pipeline.sh` (headless entry), `ingest.sh` (mechanical search→DB), `ingest-jd.sh` (land a hand-supplied JD→DB), `tailor-pending.sh`, `tailor-job.sh`, `promote.sh`, `init-db.sh`, `backfill-job-fields.py` |
| `data/` | **All personal content, gitignored:** `cv.md` (master CV), `search-profile.md` (job criteria), `references/` (style-ref CVs), `jobs.db`, `jds/`, `cvs/`, `reports/` |

## Setup

```sh
cd hiring-cafe-mcp && uv sync && cd ..
scripts/init-db.sh

# Copy the templates into data/, then edit them with your own details:
cp templates/search-profile.example.md data/search-profile.md   # your job criteria
cp templates/cv.example.md             data/cv.md               # your master CV
# Optional: drop your own tailored CVs into data/references/ as style references.
```

Everything under `data/` is gitignored, so your CV, job criteria, and scraped
JDs never enter git. Edit `scripts/ingest-jobs.py` (`TRACK_FILTERS` and the
location variants, or set `JOBS_SEARCH_LOCATION`) to match your own search.

The hiring-cafe MCP server is registered project-scoped via `.mcp.json` and
pre-approved in `.claude/settings.json` (`enableAllProjectMcpServers`), which
also carries the tight tool allowlist a headless run needs — no
permission-bypassing flags anywhere.

## Running

**Full pipeline (headless, what cron runs):**

```sh
scripts/run-pipeline.sh
```

This collects hiring.cafe (`scripts/ingest.sh`, full window on an empty DB —
override with `JOBS_INGEST_DAYS`) and then runs `/pipeline` to process the
queue. Takes a `flock` on `data/.pipeline.lock` and exits cleanly if a run is
already in progress. Reruns are idempotent: jobs are deduped by job id and never
re-triaged.

Collection and processing are separate, so a manual full run is two steps —
`/ingest-hiringcafe` (and/or `/ingest-linkedin`, `/ingest-jd`) to land jobs,
then `/pipeline` to triage → tailor → report whatever is queued.

**Nightly cron** (3:30 AM, log to file):

```cron
30 3 * * * /path/to/jobs-dashboard/scripts/run-pipeline.sh >> /path/to/jobs-dashboard/data/reports/cron.log 2>&1
```

Or as a systemd user timer, point `ExecStart` at the same script.

**Interactive use** is for reviewing, not driving runs:

- Read the latest digest in `data/reports/`.
- `/promote <job_id|company>` (or `scripts/promote.sh <job_id>`) moves a
  needs-review job to shortlisted; the next run tailors it. Add `reject` to
  reject instead. `scripts/tailor-pending.sh` tailors immediately.
- **Search hiring.cafe** with `/ingest-hiringcafe` (or `scripts/ingest.sh
  --days N`): runs the standard mechanical passes and lands new jobs as `seen`
  rows for the next `/pipeline` to triage. This is the same collection the
  nightly script runs, exposed as a standalone command.
- **Ingest a JD you found elsewhere** (a referral, a direct link) with
  `/ingest-jd <path-to-jd-file> [company] [title]`: it saves the JD, triages it
  against the profile, and tailors immediately if it scores ≥ 8 — no hiring.cafe
  search involved. To only land it in the funnel for the next run to triage,
  call `scripts/ingest-jd.sh --file … --company … --title …`.
- **Search LinkedIn** with `/ingest-linkedin`: runs a small, paced set of
  searches via the `linkedin` MCP and lands new roles as `seen` rows
  (`source:"linkedin"`); the next `/pipeline` triages, fetches JDs, and tailors
  them. On-demand only — LinkedIn is browser-scraped, so use is deliberate and
  conservative (never run in the nightly job). It needs a one-time logged-in
  cookie: run the `linkedin-scraper-mcp` login flow once if a search returns an
  auth error.
- **Fine-tune a tailored CV** by resuming its dedicated session:

  ```sh
  claude --resume "$(sqlite3 data/jobs.db "SELECT tailoring_session_id FROM jobs WHERE company LIKE '%Acme%';")"
  ```

## How a run works

**Collection** is separate from processing and lands `status = 'seen'` rows in
`data/jobs.db`, each with a compact summary — so no result can be silently lost
in model context. Three sources, each its own command:

- **hiring.cafe** (`/ingest-hiringcafe`, run by the nightly script) —
  `scripts/ingest.sh` mechanically runs eight passes (2 tracks ×
  {departments, broad query} × {local-50mi, remote}, filtered to your target
  seniority and role type), paginating to exhaustion.
- **LinkedIn** (`/ingest-linkedin`, on-demand) — a small, paced set of searches.
- **Manual** (`/ingest-jd`) — one hand-supplied JD.

Then **`/pipeline`** processes the queue (source-agnostic):

1. **Triage** — scores only `seen` rows. Hard filters (location and seniority,
   per your search profile) are pass/fail; survivors get a 1–10 score (stale
   postings score lower), recorded with rationale. ≥ 8 auto-shortlists, 6–7
   waits in needs-review, ≤ 5 is rejected. JDs for everything ≥ 6 are saved to
   disk at triage time (using the source's details tool) because postings vanish.
2. **Tailor** — every `shortlisted` job (new or promoted), capped at the 5
   highest-scoring per run. Each runs as its own headless `claude` session so
   it is independently resumable; the session id is stored on the job row.
   Outputs are drafts for review, built to PDF via `tooling/build.sh` under the
   rules in `tooling/AGENTS.md`.
3. **Report** — digest to `data/reports/run-<id>-<date>.md`: new jobs with
   scores, what was tailored, what awaits review, errors. An upstream outage
   produces an error entry in the digest and a clean exit, never a hung run.

## Job statuses

`seen → triaged` are transient; rows land as `shortlisted` (≥ 8, or promoted),
`needs-review` (6–7), or `rejected` (≤ 5, or failed a hard filter), then move
to `tailored` and eventually `applied` (manual).
