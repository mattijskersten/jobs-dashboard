# scripts/

Deterministic tooling around `data/jobs.db`. Two layers: **entry points** you
(or a command/skill) invoke directly, and **helpers** the entry points import
or wrap — you should rarely need to call a helper yourself.

## Entry points

| Script | Purpose |
|---|---|
| `run-pipeline.sh` | Headless full run: hiring.cafe collection, then `/pipeline` (triage → tailor → report). Takes a `flock` on `data/.pipeline.lock`. |
| `ingest.sh` | Mechanical hiring.cafe search → `seen` rows (wraps `ingest-jobs.py` in the MCP server's venv for httpx+yaml). |
| `ingest-jd.sh` | Land one hand-supplied JD file as a `seen` row (wraps `ingest-jd.py`). |
| `fetch-jd.sh` | Fetch one hiring.cafe job's details, save the raw JD, set `jd_path` (wraps `fetch-jd.py`). |
| `ensure-jd.sh` | Make sure one job's JD is on disk, fetching it if missing (source-aware). |
| `promote.sh` | Move a job through the funnel: promote / `reject` / `close` / `decline`. |
| `tailor-pending.sh` | Tailor all shortlisted jobs (highest score first, cap 5) in sequential headless `claude` sessions. |
| `tailor-job.sh` | Tailor one shortlisted job in its own headless session (called by `tailor-pending.sh`). |
| `refresh-tailored.sh` | Re-run tailored CVs against an updated `data/cv.md` by resuming each job's stored session. |
| `init-db.sh` | Create/migrate `data/jobs.db` from `schema.sql`. Idempotent; run at the start of every pipeline run. |
| `dashboard.sh` | Launch the web UI on 127.0.0.1:8765 (see README **Dashboard**). |
| `save-jd.py` | Persist JD text you already have (e.g. piped from the LinkedIn MCP) verbatim and set `jd_path`. |
| `ingest-linkedin.py` | Deterministic dedup + insert for LinkedIn search results (called by `/ingest-linkedin`). |

## Helpers (not called directly)

| File | Purpose |
|---|---|
| `schema.sql` | The DB schema, applied idempotently by `init-db.sh`. |
| `ingest-jobs.py`, `ingest-jd.py`, `fetch-jd.py` | Python implementations behind the same-named `.sh` wrappers. |
| `jd_store.py` | The one place a JD is written to disk (shared by every fetch path). |
| `dedup.py` | Dedup helpers shared by the ingest arms (`test_dedup.py` covers them). |
| `sanitize.py` | Shared filename-label sanitization for JD and CV artifacts. |
