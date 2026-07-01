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
| `dashboard/` | Mobile-friendly web UI over `data/jobs.db` (Starlette + uvicorn) — see **Dashboard** below |
| `.claude/commands/` | `/pipeline` (triage → tailor → report the queue); the collection commands `/ingest-hiringcafe`, `/ingest-linkedin`, `/ingest-jd`; and `/promote` |
| `tooling/` | CV build assets (`build.sh`, `cv-template.tex`, `cv-filter.lua`) and tailoring rules (`AGENTS.md`) |
| `templates/` | Sanitized templates that ship: `cv.example.md`, `search-profile.example.md`, `cv-example-{1,2}.md` |
| `scripts/` | `run-pipeline.sh` (headless entry), `ingest.sh` (mechanical search→DB; runs in `hiring-cafe-mcp/.venv` for httpx+yaml), `ingest-jd.sh` (land a hand-supplied JD→DB), `tailor-pending.sh`, `tailor-job.sh`, `promote.sh`, `init-db.sh`, `dashboard.sh` (launch the web UI) |
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

## Dashboard

A mobile-first web UI over `data/jobs.db` for reviewing the funnel from your
phone: browse and filter jobs, read JDs, preview tailored CV PDFs inline, read
each run's digest (the runs table on the overview links to `/run/{id}`, which
renders `data/reports/run-*.md`), change job state (promote / reject / reopen /
mark applied), **star a job to prioritise it** (starred jobs float to the top of
every list and have their own filter, independent of pipeline stage), and trigger
a hiring.cafe ingest or kick off tailoring for a shortlisted job — all without a
terminal. The funnel ribbon multi-selects: tap stages to toggle them on/off.

```sh
cd dashboard && uv sync && cd ..
scripts/dashboard.sh            # binds 0.0.0.0:8765 (JOBS_DASHBOARD_PORT to change)
```

Reach it from your phone over **Tailscale** at `http://<tailscale-name>:8765`
(the Crostini container's localhost isn't directly LAN-visible). For an always-on
service, install the optional user unit `dashboard/jobs-dashboard.service` (it has
its own install notes at the top).

> ⚠️ The dashboard is **unauthenticated by design** — Tailscale is the security
> boundary. It writes the database and shells out to `claude` for tailoring, so
> **never expose it to the public internet.** Ingest/tailor actions run under the
> same `flock` on `data/.pipeline.lock` as the nightly job, so they can't race it.

### Refine a tailored CV from the browser (Remote Control)

A tailored or applied job's detail page has a **Refine (Remote)** panel. Tapping it
launches a [Claude Code Remote Control](https://code.claude.com/docs/en/remote-control)
session **resumed on that job's stored `tailoring_session_id`** — i.e. the *same*
interactive Claude session that originally wrote the CV, with all its context (the JD,
your master CV, the style references, the themes it committed to). The page then shows an
**Open session** link and a **QR code**; open either on your laptop or phone and keep
fine-tuning the CV interactively, from any browser or the Claude mobile app. The CV `.md`
/ `.pdf` are overwritten in place, so the inline **Tailored CV** preview reflects your
edits. **End session** stops it (it also self-times-out after ~10 min offline).

Requirements: `claude` ≥ 2.1.51 authenticated with a **claude.ai subscription** login
(run `/status` to confirm — Remote Control rejects API-key and `setup-token` logins).
The session is a long-lived local `claude` process the dashboard launches under a PTY;
like everything else here it must stay behind Tailscale. Optionally enable mobile push
(`/config` → *Push when Claude decides*) so a finished refine turn pings your phone.

> **Ending a session leaves a stale entry in Claude Code Web.** Remote Control runs the
> session *locally* — the web/app view is just a window into it — so **End session** (and
> the ~10-min offline timeout) only kills the local `claude` process; the dashboard can't
> reach into claude.ai to tidy its session list. The now-unresponsive entry there is
> harmless: **Archive** it from the web UI to declutter (Archive is reversible; Delete is
> not, and neither is needed). Your state is never lost — the conversation lives in the
> local session transcript under `~/.claude/projects/…/<id>.jsonl`, so
> `claude --resume <tailoring_session_id>` (or launching Refine again) reopens it with
> full history regardless of what you do to the web-side entry.

State columns it relies on: every job row carries a non-null `source`
(`hiringcafe` | `linkedin` | `manual`) and a `starred` flag (0/1); run
`scripts/init-db.sh` to migrate an older DB (it adds both columns idempotently,
defaulting `source` to `hiringcafe`).

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

`seen` is transient; triage moves rows to `shortlisted` (≥ 8, or promoted),
`needs-review` (6–7), or `rejected` (≤ 5, or failed a hard filter), then move
to `tailored` and eventually `applied` (manual).
