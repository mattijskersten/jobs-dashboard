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
3. **Every job scoring ≥ 6** must end with its full description on disk at
   `data/jds/JD $COMPANY $JOBID.txt` (company name stripped of `/\:*?"<>|`)
   and `jd_path` set on the row. Tailoring and later fine-tuning read the JD
   from disk — never re-fetch it. Skip the save when the JD is already on disk
   (manual ingest sets `jd_path` at landing time).
4. Status follows the score: **≥ 8 → `shortlisted`**, **6–7 →
   `needs-review`**, **≤ 5 → `rejected`**.
5. Update rows with targeted `sqlite3` UPDATEs (double any `'` in strings):
   set score, rationale, status, jd_path (≥ 6 only), and updated_at.
