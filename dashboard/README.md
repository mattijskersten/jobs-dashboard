# jobs-dashboard (web UI)

A small, mobile-first web dashboard over `../data/jobs.db`. Browse the funnel,
read JDs, preview tailored CVs, change job state, and trigger ingest / tailoring
from your phone. See the repo root README's **Dashboard** section for how to run
it and reach it over Tailscale.

It is intentionally unauthenticated — keep it behind Tailscale (or localhost). It
writes the database and shells out to `claude` for tailoring, so it must never be
exposed publicly.
