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
  (`uvx mcp-server-linkedin@latest` login flow); do not retry in a loop.
- Read `data/search-profile.md` for the home location, the two tracks
  (A and B, as defined there), and the LinkedIn narrow-title list under its
  "Search hints" section. If it is missing, stop and tell the user to create it
  from `templates/search-profile.example.md`.

## 1. Search (sequential + paced — hard rules)

The `search_jobs` MCP returns only **~10 `job_ids` per call, regardless of
`max_pages`** (verified 2026-07-15: `max_pages` 2 and 5 both returned 10 of a
claimed 25), and its default relevance ordering is an unstable window that
shifts between identical calls and injects promoted cards. Two rules follow from
that, and shape the plan below:

- **Always pass `sort_by: "date"`.** Deterministic newest-first ordering — a
  given search returns the same set every run, and the incremental sweep
  reliably catches new postings instead of a random 10.
- **Prefer many narrow queries over one broad one.** The ~10 cap is *per query*,
  so a broad OR-of-titles search with 25+ matches silently loses most of them; a
  single-title query has a small enough pool that the ~10 window covers it.

Run two groups, **all sequential** (never parallel), and for every call use
`sort_by: "date"`, `date_posted: "past_month"`, `max_pages: 2`:

**Group 1 — broad sweep (4 calls).** OR-join each track's titles; catches the
obvious matches. `experience_level: "director,executive"`.

| Track | keywords | location | work_type |
|---|---|---|---|
| A | `<track-A titles from your profile, OR-joined>` | `<home city>` | — |
| A | `<track-A titles, OR-joined>` | `<country>` | `remote` |
| B | `<track-B titles, OR-joined>` | `<home city>` | — |
| B | `<track-B titles, OR-joined>` | `<country>` | `remote` |

**Group 2 — narrow single-title passes (3–4 calls).** One title per call, for
the variants the broad OR-query buries or that LinkedIn misclassifies below
director. **Take the title list from the "LinkedIn (narrow single-title passes)"
table in `data/search-profile.md`** — one call per row, with that row's track.
Because each pool is small, widen the filter to
`experience_level: "director,executive,mid_senior"` to recover "Head of X" roles
LinkedIn tags as Mid-Senior — the small pool keeps IC noise low. Use the
`<country>` location with **no** `work_type`, so both local and remote surface in
one call.

Keep the **total at ~7–8 calls max** — every call is a scrape and LinkedIn
bot-flags on volume. The profile list is meant to stay short for this reason; if
it has grown, run the highest-value titles and note which you dropped.

**Pacing (do not violate):**
- Call `search_jobs` **one at a time** — never issue parallel tool calls.
- ~7–8 calls total. Do **not** call `get_job_details` here (deferred to triage).

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
