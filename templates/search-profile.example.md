# Search profile — EXAMPLE

Copy this to `data/search-profile.md` and edit it for your own search:
`cp templates/search-profile.example.md data/search-profile.md`. The pipeline
reads `data/search-profile.md` (gitignored); this template ships so the repo is
usable without exposing your real criteria.

## Hard filters (pass/fail — a miss is a reject, not a lower score)

- **Location:** fully remote (anywhere hiring from your country/region), or
  your home city (hybrid and on-site both fine). Anything else — including
  "remote, other-region only" — fails.
- **Seniority:** the level you are targeting. Below it fails, even strong roles.
  State whether people management is required or merely preferred.
- **Role, track A — <your first track, e.g. product leadership at a tech company>:**
  list the titles that qualify (e.g. CPO / VP / Senior Director / Director of Product).
- **Role, track B — <your second track, e.g. IT leadership at a non-tech company>:**
  list the titles and the kind of company that qualifies.

A job must fit one of the two tracks. Record which track it matched.

## Soft preferences (drive the 1–10 score for jobs that pass)

Describe what makes a role a strong fit for you, derived from your CV:

- **Domain fit (track A):** the product/domain areas you are strongest in.
- **Domain fit (track B):** the second-track domain areas you are strongest in.
- **Scope:** org size, revenue responsibility, P&L ownership, seniority of
  stakeholders — bigger is better.
- **People management:** how much a real team to lead matters to you.
- **Other pluses:** specific skills, industries, or company stages you favor.
- **Company stage:** the stages (startup → enterprise) that fit you.

## Scoring guide

Posting freshness: a posting older than 60 days (per its `posted` date) loses
1 point, older than 90 days loses 2 — old-but-live postings often mean a slow
or stalled process. Say so in the rationale when it changes the bucket.

- **9–10:** track and domain both dead-on, right seniority, scope ideal.
- **8:** strong track + domain fit, minor gaps.
- **6–7:** passes hard filters but domain or scope is a stretch → needs-review.
- **≤5:** passes hard filters but weak fit → reject.

## Search hints

The two collectors have opposite search rules — a broad filter for hiring.cafe,
narrow single-title passes for LinkedIn — because their APIs differ (hiring.cafe
paginates to exhaustion; LinkedIn caps output at ~10 results per call). Read the
subsection for the collector you are running.

### hiring.cafe (script-driven — broad filter)

These passes are implemented mechanically in `scripts/ingest-jobs.py` — the
pipeline runs that script rather than issuing `search_jobs` calls, so results
land in the database deterministically. Keep this section and the script in
sync when tuning the strategy.

Do **not** search by `job_title` lists — title phrase matching misses variants.
Filter broadly and let triage do the precision work. Every pass uses
`seniority_levels: ["Senior Level"]` and `role_types: ["People Manager"]`
(adjust to your target level / whether you require people management).

Four passes per track — a `departments` pass and a broad `query` pass, each for
your local area and for remote. The departments facet is high-precision but has
classification gaps, so the two passes must be unioned, not chosen between.
Edit `TRACK_FILTERS` and the location variants in `scripts/ingest-jobs.py` to
match your tracks and home location, then keep this table in sync:

| Track | Facet pass | Broad pass |
|---|---|---|
| A | `departments: ["<your dept>"]` | `query: "<broad terms>"` |
| B | `departments: ["<your dept>"]` | `query: "<broad terms>"` |

Location, two variants per pass:

- **Local:** `location: "<Your City, Country>"`, `location_radius_miles: 50`.
- **Remote:** `location: "<Your City, Country>"` (no radius) with
  `workplace_types: ["Remote"]` — check each job's stated hiring region at
  triage anyway.

Paginate every pass to exhaustion. Use `page_size: 50` to minimize calls.

### LinkedIn (narrow single-title passes)

`/ingest-linkedin` cannot use the broad filter above: LinkedIn's `search_jobs`
returns only ~10 results per call, so a broad OR-of-titles query silently drops
most matches. It runs a broad sweep (OR-joined track titles, from the Role lines
above) **plus** a short list of narrow single-title passes — one title per call,
small enough to fit under the ~10 cap — for the highest-value titles and the
variants the OR-query buries. Tune this list; keep it short (the skill caps total
calls at ~7–8 to avoid LinkedIn's bot protection):

| Track | Title |
|---|---|
| A | `<a high-value / commonly-missed title, e.g. Head of Product>` |
| B | `<a high-value / commonly-missed title, e.g. IT Director>` |

This is the *what*. The *how* (sort order, seniority facet, call ceiling,
pacing) lives in `.claude/commands/ingest-linkedin.md`, which reads this list.
