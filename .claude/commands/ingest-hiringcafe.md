---
description: Search hiring.cafe and land matching jobs in the pipeline as 'seen'
---

Collect jobs from hiring.cafe into `data/jobs.db` as `seen` rows, mechanically
and deterministically. This is the hiring.cafe arm of collection — the symmetric
partner of `/ingest-linkedin` and `/ingest-jd`. You only collect here; triage and
tailoring happen later in `/pipeline`.

## Run it

```
scripts/ingest.sh --days <N>
```

It executes the eight standard passes from the profile's search hints
(2 tracks × {departments, broad query} × {local-50mi, remote}), paginates to
exhaustion, dedupes against the database, and inserts every unseen hit as a
`status = 'seen'` row with its compact summary in `summary_json` — so no result
can be lost in model context. It leaves `first_seen_run_id` NULL; the next
`/pipeline` run claims the queue and attributes these jobs to that run.

Choosing `<N>` (the `posted_within_days` window):

- **7** — the normal incremental window. Use this by default.
- **121** — the site's full window. Use when the database is empty, or the user
  asked for a backfill. (Check emptiness:
  `sqlite3 data/jobs.db "SELECT count(*) FROM jobs;"`.)

Do **not** issue your own `search_jobs` MCP calls for collection — the script is
the source of truth so collection stays deterministic.

## Report

Capture the script's stdout and print a short summary: the window used, how many
unique jobs were found across passes, how many were already known, and how many
were inserted as `seen`. Exit code 2 means a partial ingest (some passes failed,
e.g. a Vercel block) — report the failed passes; the rows that did land are still
valid. Remind the user these are `seen` rows that the next `/pipeline` run will
triage and tailor. Do not open or finalize a `runs` row — this is collection only.
