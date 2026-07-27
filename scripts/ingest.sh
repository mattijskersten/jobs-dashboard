#!/usr/bin/env bash
# Run the mechanical search ingestion with the MCP server's venv (has curl_cffi).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/hiring-cafe-mcp/.venv/bin/python3" "$ROOT/scripts/ingest-jobs.py" "$@"
