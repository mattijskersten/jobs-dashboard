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
`{ title, company, location, posted }`. The canonical id is the numeric
`job_id`; the posting URL is `https://www.linkedin.com/jobs/view/<job_id>/`.

## 2. De-dupe, then land each hit as `seen`

Load what is already known:
`sqlite3 -json data/jobs.db "SELECT job_id, company, title FROM jobs;"`

For each parsed LinkedIn record, in order, **write it immediately** (don't hold
the whole batch in memory) unless it is a duplicate:

1. **Exact:** skip if `job_id = 'linkedin-<id>'` already exists.
2. **Cross-source:** skip if an existing row (e.g. from hiring.cafe) is the same
   role — same *normalized* company and a similar title. Normalize by
   lowercasing and stripping punctuation and company suffixes (inc/ltd/gmbh/
   sp z o o…); for titles also drop remote/hybrid/city words. Treat title
   similarity ≳ 0.6 as a match. Log every skip with the matched existing job.

Insert survivors (escape `'` as `''`):

```
INSERT OR IGNORE INTO jobs
  (job_id, company, title, url, apply_url, track, status, posted_date,
   summary_json, first_seen_run_id)
VALUES ('linkedin-<id>', '<company>', '<title>',
   'https://www.linkedin.com/jobs/view/<id>/',
   'https://www.linkedin.com/jobs/view/<id>/', '<A|B>', 'seen',
   <posted_date-or-NULL>, '<summary_json>', NULL);
```

`summary_json` must be valid JSON:
`{"source":"linkedin","linkedin_id":"<id>","title":...,"company":...,`
`"location":...,"posted":...,"url":...}`. Set `posted_date` only if `posted`
gives a real date; LinkedIn often shows "2 weeks ago" — leave NULL then.
`track` = A for the product searches, B for the IT searches.

## 3. Report

Print a short summary: number of searches run, total hits, how many were new
(inserted), how many skipped as exact or cross-source duplicates (name the
matched job for cross-source skips), and a table of the **new** rows
(company, title, track, location, url). End by reminding the user these are
`seen` rows that the next `/pipeline` run will triage, fetch JDs for (≥6), and
tailor (≥8). Do not open or finalize a `runs` row — this is a collection step.
