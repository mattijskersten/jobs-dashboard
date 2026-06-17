# jobs-dashboard

CV-driven job search agent. A nightly pipeline searches
[hiring.cafe](https://hiring.cafe) for senior product-leadership and
IT-leadership roles, triages them against `agent/search-profile.md`, tailors
your CV for the best matches in parallel headless Claude sessions, and writes a
standalone digest. All state lives in a SQLite database designed to back a
future dashboard.

Your personal content — your CV, job criteria, scraped JDs, tailored CVs, and
the database — is gitignored; the repo ships `*.example.*` templates you copy
into place (see **Setup**). Nothing personal is committed.

## Layout

| Path | Purpose |
|---|---|
| `hiring-cafe-mcp/` | MCP server for the unofficial hiring.cafe API (see its README) |
| `agent/search-profile.md` | Hard filters, soft preferences, scoring guide — the triage source of truth (your copy of `search-profile.example.md`; gitignored) |
| `.claude/commands/pipeline.md` | `/pipeline` — one full run: search → triage → tailor → report |
| `.claude/commands/promote.md` | `/promote` — move a needs-review job to shortlisted |
| `cv/` | CV build assets, tailoring rules (`cv/AGENTS.md`), `cv.example.md` + `examples/` templates (your real `cv.md` is gitignored) |
| `scripts/` | `run-pipeline.sh` (headless entry), `ingest.sh` (mechanical search→DB), `ingest-jd.sh` (land a hand-supplied JD→DB), `tailor-pending.sh`, `tailor-job.sh`, `promote.sh`, `init-db.sh`, `backfill-job-fields.py` |
| `data/` | Runtime state (gitignored): `jobs.db`, saved JDs (`jds/`), tailored CVs (`cvs/`), per-run digests (`reports/`) |

## Setup

```sh
cd hiring-cafe-mcp && uv sync && cd ..
scripts/init-db.sh

# Copy the templates into place, then edit them with your own details:
cp agent/search-profile.example.md agent/search-profile.md   # your job criteria
cp cv/cv.example.md cv/cv.md                                  # your master CV
# Optional: drop your own tailored CVs into cv/examples/ as style references.
```

Your real `agent/search-profile.md`, `cv/cv.md`, `cv/examples/*` (except the
shipped `example-*.md`), and everything under `data/` are gitignored, so your
CV and job criteria never enter git. Edit `scripts/ingest-jobs.py`
(`TRACK_FILTERS` and the location variants) to match your own search.

The hiring-cafe MCP server is registered project-scoped via `.mcp.json` and
pre-approved in `.claude/settings.json` (`enableAllProjectMcpServers`), which
also carries the tight tool allowlist a headless run needs — no
permission-bypassing flags anywhere.

## Running

**Full pipeline (headless, what cron runs):**

```sh
scripts/run-pipeline.sh
```

Takes a `flock` on `data/.pipeline.lock` and exits cleanly if a run is already
in progress. Reruns are idempotent: jobs are deduped by hiring.cafe job id and
never re-triaged.

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
- **Ingest a JD you found elsewhere** (LinkedIn, a referral, a direct link)
  with `/ingest-jd <path-to-jd-file> [company] [title]`: it saves the JD,
  triages it against the profile, and tailors immediately if it scores ≥ 8 —
  no hiring.cafe search involved. To only land it in the funnel for the next
  run to triage, call `scripts/ingest-jd.sh --file … --company … --title …`.
- **Fine-tune a tailored CV** by resuming its dedicated session:

  ```sh
  claude --resume "$(sqlite3 data/jobs.db "SELECT tailoring_session_id FROM jobs WHERE company LIKE '%Acme%';")"
  ```

## How a run works

1. **Search** — `scripts/ingest.sh` mechanically runs eight hiring.cafe
   passes (2 tracks × {departments, broad query} × {local-50mi, remote},
   always Senior Level + People Manager), paginates to exhaustion, and
   inserts every unseen hit as a `seen` row with its compact summary — so
   no result can be silently lost in model context.
2. **Triage** — the agent scores only `seen` rows from the database. Hard
   filters (location and seniority, per your search profile) are pass/fail;
   survivors get a 1–10 score (stale postings score lower). Every job is
   recorded with score and rationale. ≥ 8 auto-shortlists, 6–7 waits in
   needs-review, ≤ 5 is rejected. JDs for everything ≥ 6 are saved to disk
   at triage time because postings disappear.
3. **Tailor** — every `shortlisted` job (new or promoted), capped at the 5
   highest-scoring per run. Each runs as its own headless `claude` session so
   it is independently resumable; the session id is stored on the job row.
   Outputs are drafts for review, built to PDF via `cv/build.sh` under the
   rules in `cv/AGENTS.md`.
4. **Report** — digest to `data/reports/run-<id>-<date>.md`: new jobs with
   scores, what was tailored, what awaits review, errors. The hiring.cafe API
   is unofficial; an outage produces an error entry in the digest and a clean
   exit, never a hung run.

## Job statuses

`seen → triaged` are transient; rows land as `shortlisted` (≥ 8, or promoted),
`needs-review` (6–7), or `rejected` (≤ 5, or failed a hard filter), then move
to `tailored` and eventually `applied` (manual).
