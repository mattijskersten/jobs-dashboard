#!/usr/bin/env bash
# Create/migrate data/jobs.db. Idempotent — safe to run at the start of every pipeline run.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/data/jds" "$ROOT/data/reports" "$ROOT/data/cvs" "$ROOT/data/references"
sqlite3 "$ROOT/data/jobs.db" < "$ROOT/scripts/schema.sql"

# Migrations for databases created before a column existed in schema.sql
# (CREATE TABLE IF NOT EXISTS does not alter existing tables).
for col in posted_date apply_url summary_json; do
  if ! sqlite3 "$ROOT/data/jobs.db" "PRAGMA table_info(jobs);" | grep -q "|$col|"; then
    sqlite3 "$ROOT/data/jobs.db" "ALTER TABLE jobs ADD COLUMN $col TEXT;"
  fi
done

# source: added later. ALTER cannot carry the CHECK constraint schema.sql
# declares, but the NOT NULL default keeps every row non-null. The ingest
# writers set it explicitly on every new row.
if ! sqlite3 "$ROOT/data/jobs.db" "PRAGMA table_info(jobs);" | grep -q "|source|"; then
  sqlite3 "$ROOT/data/jobs.db" "ALTER TABLE jobs ADD COLUMN source TEXT NOT NULL DEFAULT 'hiringcafe';"
fi

# starred: manual priority flag, added later.
if ! sqlite3 "$ROOT/data/jobs.db" "PRAGMA table_info(jobs);" | grep -q "|starred|"; then
  sqlite3 "$ROOT/data/jobs.db" "ALTER TABLE jobs ADD COLUMN starred INTEGER NOT NULL DEFAULT 0;"
fi

# Status vocabulary: SQLite cannot alter a CHECK constraint, so tables created
# before a status was added must be rebuilt. One transaction: create the new
# table (DDL matches schema.sql — keep in sync), copy rows, swap. Runs after the
# column migrations above so every copied column is guaranteed to exist.
# The grep sentinel is the most recently added status ('declined') — bump it
# whenever you add another, or this rebuild silently no-ops on existing DBs and
# the new value fails the CHECK at runtime.
if ! sqlite3 "$ROOT/data/jobs.db" \
     "SELECT sql FROM sqlite_master WHERE type='table' AND name='jobs';" \
     | grep -q "'declined'"; then
  sqlite3 -bail "$ROOT/data/jobs.db" <<'SQL'
BEGIN IMMEDIATE;
CREATE TABLE jobs_new (
    job_id              TEXT PRIMARY KEY,
    company             TEXT NOT NULL,
    title               TEXT NOT NULL,
    url                 TEXT,
    apply_url           TEXT,
    track               TEXT CHECK (track IN ('A', 'B')),
    source              TEXT NOT NULL DEFAULT 'hiringcafe'
                        CHECK (source IN ('hiringcafe', 'linkedin', 'manual')),
    status              TEXT NOT NULL DEFAULT 'seen'
                        CHECK (status IN ('seen','triaged','needs-review',
                                          'shortlisted','tailored','applied','rejected',
                                          'closed','declined')),
    score               INTEGER CHECK (score BETWEEN 1 AND 10),
    starred             INTEGER NOT NULL DEFAULT 0,
    rationale           TEXT,
    posted_date         TEXT,
    summary_json        TEXT,
    jd_path             TEXT,
    cv_md_path          TEXT,
    cv_pdf_path         TEXT,
    tailoring_session_id TEXT,
    first_seen_run_id   INTEGER REFERENCES runs(run_id),
    date_seen           TEXT NOT NULL DEFAULT (datetime('now')),
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT INTO jobs_new (job_id, company, title, url, apply_url, track, source,
                      status, score, starred, rationale, posted_date,
                      summary_json, jd_path, cv_md_path, cv_pdf_path,
                      tailoring_session_id, first_seen_run_id, date_seen,
                      created_at, updated_at)
  SELECT job_id, company, title, url, apply_url, track, source,
         status, score, starred, rationale, posted_date,
         summary_json, jd_path, cv_md_path, cv_pdf_path,
         tailoring_session_id, first_seen_run_id, date_seen,
         created_at, updated_at
  FROM jobs;
DROP TABLE jobs;
ALTER TABLE jobs_new RENAME TO jobs;
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_score  ON jobs(score);
COMMIT;
SQL
  echo "migrated: jobs table rebuilt to allow status 'declined'"
fi

echo "ok: $ROOT/data/jobs.db"
