#!/usr/bin/env python3
"""Mechanical search ingestion: run the standard hiring.cafe passes and
insert every unseen hit as a `seen` row in data/jobs.db.

This replaces LLM-driven search collection, which silently dropped results
when hundreds of hits flowed through model context. Search → DB is now
deterministic; the pipeline's LLM only scores rows that are already safely
stored (status = 'seen', summary in summary_json).

Usage (via scripts/ingest.sh, which supplies the right interpreter):

    scripts/ingest.sh [--days N] [--run-id ID]

--days    posted_within_days window (default 7; use 121 for backfill)
--run-id  runs.run_id to stamp on first_seen_run_id

Passes (from data/search-profile.md): for each track, a departments pass
and a broad query pass, each in a local-50mi and a remote variant — always
Senior Level + People Manager. Requests are paced at 1/s (unofficial API;
heavier bursts have triggered Vercel bot protection).
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hiring-cafe-mcp" / "src"))

from hiring_cafe_mcp.api import HiringCafeClient, HiringCafeError  # noqa: E402
from hiring_cafe_mcp.server import _dedupe, _summarize_hit  # noqa: E402

# TODO(#1): SEARCH_LOCATION and TRACK_FILTERS below are the live search
# config but are hardcoded here (the script does not read data/search-profile.md).
# To make the repo fully generic, load tracks + location from a gitignored
# data/ config (e.g. data/search-config.yaml) with a shipped templates/ example,
# then remove these personal defaults. Behaviour-affecting — validate with a real
# ingest run after changing. (The command files and compare-linkedin.py were
# already genericized; this is the remaining piece.)

# Your search anchor location — override with JOBS_SEARCH_LOCATION, or edit here.
SEARCH_LOCATION = os.environ.get("JOBS_SEARCH_LOCATION", "Berlin, Germany")

TRACK_FILTERS = {
    "A": [
        {"departments": ["Product Management"]},
        {"searchQuery": "product"},
    ],
    "B": [
        {"departments": ["Information Technology"]},
        {"searchQuery": "IT information technology"},
    ],
}
MAX_SERVER_PAGES = 25  # safety stop: 25 × 40 = 1000 unique jobs per pass


def run_pass(client, base_state: dict, days: int, label: str) -> tuple[dict, str | None]:
    """One paginated pass. Returns ({requisition_id: summary}, error)."""
    state = {
        **base_state,
        "seniorityLevel": ["Senior Level"],
        "roleTypes": ["People Manager"],
        "dateFetchedPastNDays": days,
    }
    out: dict[str, dict] = {}
    for page in range(MAX_SERVER_PAGES):
        time.sleep(1)  # pace every call; unofficial API, avoid rate limits
        try:
            props = client.search(state, page)
        except HiringCafeError as exc:
            if page > 0:  # partial results are still worth keeping
                print(f"  {label}: ERROR on page {page} after {len(out)} jobs: {exc}")
                return out, f"{label}: page {page}: {exc}"
            print(f"  {label}: ERROR: {exc}")
            return out, f"{label}: {exc}"
        hits = props.get("ssrHits") or []
        for hit, n in _dedupe(hits):
            summary = _summarize_hit(hit, n)
            if summary.get("id"):
                out.setdefault(summary["id"], summary)
        if props.get("ssrIsLastPage") or not hits:
            break
    print(f"  {label}: {len(out)} unique jobs")
    return out, None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--run-id", type=int, default=None)
    args = ap.parse_args()

    client = HiringCafeClient()
    local = client.resolve_location(SEARCH_LOCATION, radius_miles=50)
    remote = client.resolve_location(SEARCH_LOCATION)
    if not local or not remote:
        sys.exit(f"could not resolve {SEARCH_LOCATION}")

    variants = [
        ("local", {"locations": [local]}),
        ("remote", {"locations": [remote], "workplaceTypes": ["Remote"]}),
    ]

    jobs: dict[str, tuple[str, dict]] = {}  # id -> (track, summary)
    errors: list[str] = []
    print(f"ingest: window {args.days} days")
    for track, filter_list in TRACK_FILTERS.items():
        for base in filter_list:
            for vname, vstate in variants:
                fname = next(iter(base))
                label = f"track {track} / {fname} / {vname}"
                found, err = run_pass(client, {**base, **vstate}, args.days, label)
                if err:
                    errors.append(err)
                for jid, summary in found.items():
                    jobs.setdefault(jid, (track, summary))

    db = sqlite3.connect(ROOT / "data" / "jobs.db")
    known = {r[0] for r in db.execute("SELECT job_id FROM jobs")}
    new = {jid: v for jid, v in jobs.items() if jid not in known}

    with db:  # one transaction
        for jid, (track, s) in new.items():
            db.execute(
                "INSERT OR IGNORE INTO jobs (job_id, company, title, url,"
                " apply_url, track, status, posted_date, summary_json,"
                " first_seen_run_id) VALUES (?,?,?,?,?,?,'seen',?,?,?)",
                (
                    jid,
                    s.get("company") or "(unknown)",
                    s.get("title") or "(unknown)",
                    s.get("url"),
                    s.get("apply_url"),
                    track,
                    s.get("posted"),
                    json.dumps(s, ensure_ascii=False),
                    args.run_id,
                ),
            )

    print(
        f"\ningest done: {len(jobs)} unique jobs across passes, "
        f"{len(known & jobs.keys())} already known, {len(new)} inserted as 'seen'"
    )
    if errors:
        print("errors (partial ingest, digest must mention these):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
