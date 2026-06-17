#!/usr/bin/env bash
# Land a manually-provided JD file in data/jobs.db as a `seen` row.
# Pure stdlib; no hiring.cafe API call. See scripts/ingest-jd.py for args.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec python3 "$ROOT/scripts/ingest-jd.py" "$@"
