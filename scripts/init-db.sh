#!/usr/bin/env bash
# Create/migrate data/jobs.db. Idempotent — safe to run at the start of every pipeline run.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/data/jds" "$ROOT/data/reports" "$ROOT/data/cvs"
sqlite3 "$ROOT/data/jobs.db" < "$ROOT/scripts/schema.sql"

# Migrations for databases created before a column existed in schema.sql
# (CREATE TABLE IF NOT EXISTS does not alter existing tables).
for col in posted_date apply_url summary_json; do
  if ! sqlite3 "$ROOT/data/jobs.db" "PRAGMA table_info(jobs);" | grep -q "|$col|"; then
    sqlite3 "$ROOT/data/jobs.db" "ALTER TABLE jobs ADD COLUMN $col TEXT;"
  fi
done

echo "ok: $ROOT/data/jobs.db"
