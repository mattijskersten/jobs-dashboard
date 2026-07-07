---
description: Search LinkedIn for relevant jobs and land them in the pipeline as 'seen'
---

Pull senior-leadership jobs from LinkedIn into the same `data/jobs.db` funnel as
hiring.cafe, **conservatively** — LinkedIn is scraped through a real browser and
will bot-flag on heavy use. You only collect here; triage happens later in
`/pipeline`. Never call the LinkedIn person/messaging tools — only
`mcp__linkedin__search_jobs` (and, later in triage, `get_job_details`).

## 0. Preconditions

- `scripts/init-db.sh` (idempotent).
- The `linkedin` MCP needs a logged-in session cookie. If a search returns an
  auth error, stop and tell the user to run the one-time login
  (`uvx linkedin-scraper-mcp@latest` login flow); do not retry in a loop.
- Read `data/search-profile.md` for the home location and the two tracks
  (A and B, as defined there). If it is missing, stop and tell
  the user to create it from `templates/search-profile.example.md`.

## 1. Search (sequential + paced — hard rules)

Run a small fixed set of **~4 searches**, derived from the profile's tracks and
location. Mirror this validated pattern (fill keywords and location from the
profile — OR-join each track's qualifying titles):

| Track | keywords | location | work_type |
|---|---|---|---|
| A | `<track-A titles from your profile, OR-joined>` | `<home city>` | — |
| A | `<track-A titles, OR-joined>` | `<country>` | `remote` |
| B | `<track-B titles, OR-joined>` | `<home city>` | — |
| B | `<track-B titles, OR-joined>` | `<country>` | `remote` |

For every call to `mcp__linkedin__search_jobs` use:
`max_pages: 2`, `experience_level: "director,executive"`, `date_posted: "past_month"`
(and `work_type` per the table).

**Pacing (do not violate):**
- Call `search_jobs` **one at a time** — never issue parallel tool calls.
- ~4 calls total. Do **not** call `get_job_details` here (deferred to triage).

`search_jobs` returns `{ job_ids: [...], sections: {name -> raw text}, url }`.
Parse the raw `sections` text into one record per `job_id`:
`{ id, title, company, location, posted, track }` — `id` is the numeric
`job_id`, `track` is `A` for the product searches and `B` for the IT searches.
This parsing (messy text → structured records) is your only job with the
results; the dedup and insert are **not** yours to reason through — hand the
records to the script below, which owns them deterministically.

## 2. De-dupe + land as `seen` — via `scripts/ingest-linkedin.py`

Collect the parsed records from **all** searches into one JSON array and pipe it
to the script. It loads what is already known, applies the fixed dedup rule, and
inserts survivors as `status = 'seen'`, `first_seen_run_id = NULL`:

```
echo '<json-array-of-records>' | scripts/ingest-linkedin.py
```

Each record is `{"id","title","company","location","posted","track"}`. Pass
`posted` verbatim (e.g. `"13 hours ago"`, `"5 days ago"`, or a real date); the
script keeps `posted_date` only when it parses to an ISO date and leaves it NULL
otherwise. Do **not** write your own `INSERT`s or `sqlite3` dedup queries — the
script (and its shared logic in `scripts/dedup.py`, pinned by
`scripts/test_dedup.py`) is the single source of truth so LinkedIn dedups the
same way on every run.

The dedup rule the script enforces, for reference:

1. **Exact:** skip if `job_id = 'linkedin-<id>'` already exists (also collapses
   a job returned by more than one search).
2. **Cross-source:** skip if an existing row (e.g. from hiring.cafe) is the same
   role — identical *normalized* company and title Jaccard ≥ 0.6. It cannot
   catch recruiter-fronted listings that hide the real employer; those survive.

Capture the script's stdout — it reports counts and names every skip and insert.

## 3. Report

Print a short summary from the script's stdout: number of searches run, total
hits, how many were new (inserted), how many skipped as exact or cross-source
duplicates (name the matched job for cross-source skips), and a table of the
**new** rows (company, title, track, location, url). End by reminding the user these are
`seen` rows that the next `/pipeline` run will triage, fetch JDs for (≥6), and
tailor (≥8). Do not open or finalize a `runs` row — this is a collection step.
