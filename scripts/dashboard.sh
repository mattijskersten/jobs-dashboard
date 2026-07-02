#!/usr/bin/env bash
# Launch the jobs dashboard (Starlette + uvicorn) over data/jobs.db.
#
# Binds 127.0.0.1:8765; remote access goes through Tailscale Serve
# (`tailscale serve --bg --https=443 http://127.0.0.1:8765`), which proxies
# https://<node>.<tailnet>.ts.net to it — tailnet-only, with TLS. The app is
# UNAUTHENTICATED and writes the DB + runs `claude` for tailoring — never
# expose it publicly (no Funnel, no 0.0.0.0 on an untrusted LAN).
#
#   scripts/dashboard.sh                 # 127.0.0.1:8765
#   JOBS_DASHBOARD_PORT=9000 scripts/dashboard.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# The dashboard resolves data/ relative to the repo root; pin it so the app works
# the same whether launched from here or from a worktree.
export JOBS_DASHBOARD_ROOT="$ROOT"
export JOBS_DASHBOARD_HOST="${JOBS_DASHBOARD_HOST:-127.0.0.1}"
export JOBS_DASHBOARD_PORT="${JOBS_DASHBOARD_PORT:-8765}"

cd "$ROOT/dashboard"
exec uv run uvicorn jobs_dashboard.app:app \
  --host "$JOBS_DASHBOARD_HOST" --port "$JOBS_DASHBOARD_PORT"
