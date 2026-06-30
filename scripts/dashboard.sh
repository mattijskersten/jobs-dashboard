#!/usr/bin/env bash
# Launch the jobs dashboard (Starlette + uvicorn) over data/jobs.db.
#
# Binds 0.0.0.0:8765 so it is reachable from a phone over Tailscale. It is
# UNAUTHENTICATED and writes the DB + runs `claude` for tailoring — keep it
# behind Tailscale/localhost, never expose it publicly.
#
#   scripts/dashboard.sh                 # 0.0.0.0:8765
#   JOBS_DASHBOARD_PORT=9000 scripts/dashboard.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# The dashboard resolves data/ relative to the repo root; pin it so the app works
# the same whether launched from here or from a worktree.
export JOBS_DASHBOARD_ROOT="$ROOT"
export JOBS_DASHBOARD_HOST="${JOBS_DASHBOARD_HOST:-0.0.0.0}"
export JOBS_DASHBOARD_PORT="${JOBS_DASHBOARD_PORT:-8765}"

cd "$ROOT/dashboard"
exec uv run uvicorn jobs_dashboard.app:app \
  --host "$JOBS_DASHBOARD_HOST" --port "$JOBS_DASHBOARD_PORT"
