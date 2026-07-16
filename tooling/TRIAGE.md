# Triage rules — scoring a `seen` job row

The single definition of how a job is scored and which status it lands in.
Both `/pipeline` (batch) and `/ingest-jd` (single manual JD) apply these rules —
change them here, not in the command files. `data/search-profile.md` supplies
the candidate-specific criteria (hard filters, soft preferences, scoring
guide); read it first — it is the source of truth for *what* to score against,
this file for *how* the score becomes a status.

1. **Hard filters are pass/fail** (location, seniority, track fit — per the
   search profile). A miss is `rejected` with score 1 and a one-line rationale
   naming the failed filter. Never fetch details for a hard-filter reject.
   Correct `track` (A or B, per the profile's tracks) if the ingest's guess is
   wrong or it is unset.
2. Jobs that pass score **1–10** against the profile's soft preferences and
   scoring guide (domain, scope, people management, posting freshness — stale
   postings score lower per the profile).
3. **The JD is saved to disk by the tooling at fetch time — you never write or
   reformat JD text.** Whenever you fetch a job's details you must persist them
   verbatim so tailoring and later fine-tuning read full-fidelity source text
   (they read the JD from disk and never re-fetch):
   - **hiring.cafe** — fetch via `scripts/fetch-jd.sh <job_id> --company "<name>"`
     (not the MCP tool). It writes the raw description to
     `data/jds/JD <company> <job_id>.txt` and sets `jd_path` for you; score from
     its structured stdout.
   - **linkedin** — call `mcp__linkedin__get_job_details`, then pipe its
     `description` field **verbatim** (no edits, no headers, no summarizing) to
     `scripts/save-jd.py --job-id <job_id> --company "<name>"`, which writes it
     and sets `jd_path`.
   - **manual** — already on disk with `jd_path` set at landing time; skip.

   Every scoring-≥ 6 job must have its JD on disk. A fetched job is always saved,
   so an ambiguous fetch that ends up < 6 still leaves its raw JD on disk — that
   is fine (re-triage never re-fetches).
4. Status follows the score: **≥ 8 → `shortlisted`**, **6–7 →
   `needs-review`**, **≤ 5 → `rejected`**.
5. Update rows with targeted `sqlite3` UPDATEs (double any `'` in strings):
   set score, rationale, status, and updated_at. `jd_path` is already set by
   the fetch tooling (rule 3) — do not set it by hand.
