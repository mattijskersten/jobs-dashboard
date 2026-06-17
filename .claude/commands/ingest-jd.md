---
description: Ingest one manually-provided JD file, triage it, and tailor if it scores high
argument-hint: <path-to-jd-file> [company] [title]
---

Bring a single job description that the user provides as a file into the same
funnel a hiring.cafe job goes through — but with no search, no API call, and
the JD already in hand. Arguments: `$ARGUMENTS` (first token is the JD file
path; any remaining text is an optional company / title hint).

## 1. Read and identify the job

- Read the JD file named in the first argument. If no path was given, ask the
  user for one and stop.
- Determine **company** and **title**. Use the hint in `$ARGUMENTS` if present;
  otherwise infer them from the JD text. Also pull, if clearly stated in the
  JD: **location**, **workplace type** (Remote/Hybrid/Onsite), the posting
  **URL**, the **apply link**, and a **posted date**. Leave anything genuinely
  unknown unset — do not invent it.

## 2. Land it in the database

Run `scripts/init-db.sh` (idempotent), then land the JD as a `seen` row:

```
scripts/ingest-jd.sh --file "<path>" --company "<company>" --title "<title>" \
  [--url "<url>"] [--apply-url "<apply>"] [--location "<loc>"] \
  [--workplace-type "<type>"] [--posted-date "<YYYY-MM-DD>"]
```

This saves the JD to `data/jds/` and inserts/refreshes the row with `jd_path`
set and `summary_json.source = "manual"`. Note the printed `job_id`.

## 3. Triage it

Read `agent/search-profile.md`, then score this one job exactly as the
`/pipeline` triage does — but the full JD is already on disk, so read it from
`jd_path` for your judgment and do **not** call `get_job_details` (there is no
hiring.cafe id to fetch).

1. **Hard filters are pass/fail** (location, seniority, and track fit per your
   search profile). A miss → `status='rejected'`, score 1, one-line rationale
   naming the failed filter.
2. Otherwise score 1–10 against the profile's soft preferences. Set `track`
   (A = product leadership, B = IT leadership) if not already set.
3. Update the row (escape `'` as `''`): set score, rationale, updated_at, and
   `status` = `shortlisted` (≥8) / `needs-review` (6–7) / `rejected` (≤5).

## 4. Tailor if shortlisted

If the row is now `shortlisted`, tailor it immediately:
`scripts/tailor-job.sh <job_id>`. Otherwise skip tailoring.

## 5. Report

Print a short summary: company, title, score, resulting status, the one-line
rationale, and — if tailored — the CV PDF path and `claude --resume <id>`
command; if it only reached needs-review, the `scripts/promote.sh <job_id>`
command. This is a manual one-off: do not open or finalize a `runs` row.
