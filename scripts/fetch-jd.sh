#!/usr/bin/env bash
# Fetch one hiring.cafe job's details and save its raw JD to disk (sets jd_path).
# Uses the MCP server's venv (has curl_cffi), like scripts/ingest.sh. See
# scripts/fetch-jd.py for args.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/hiring-cafe-mcp/.venv/bin/python3" "$ROOT/scripts/fetch-jd.py" "$@"
