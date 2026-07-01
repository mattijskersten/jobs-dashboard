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

Passes (from data/search-config.yaml — copy templates/search-config.example.yaml
and edit): for each track, every configured filter (departments or query) runs
in a local-radius and a remote variant, with the configured seniority/role-type
facets. Requests are paced at 1/s (unofficial API; heavier bursts have
triggered Vercel bot protection).
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hiring-cafe-mcp" / "src"))

from hiring_cafe_mcp.api import HiringCafeClient, HiringCafeError  # noqa: E402
from hiring_cafe_mcp.server import _dedupe, _summarize_hit  # noqa: E402

CONFIG_PATH = ROOT / "data" / "search-config.yaml"
MAX_SERVER_PAGES = 25  # safety stop: 25 × 40 = 1000 unique jobs per pass


def load_config() -> dict:
    """Parse data/search-config.yaml into the shape the passes need."""
    if not CONFIG_PATH.is_file():
        sys.exit(
            f"missing {CONFIG_PATH} — copy templates/search-config.example.yaml"
            " there and fill in your search"
        )
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    location = os.environ.get("JOBS_SEARCH_LOCATION") or raw.get("location")
    if not location:
        sys.exit(f"{CONFIG_PATH}: 'location' is required")
    tracks = raw.get("tracks") or {}
    if not tracks:
        sys.exit(f"{CONFIG_PATH}: at least one entry under 'tracks' is required")
    track_filters: dict[str, list[dict]] = {}
    for track, entries in tracks.items():
        filters = []
        for entry in entries or []:
            if not isinstance(entry, dict) or len(entry) != 1:
                sys.exit(
                    f"{CONFIG_PATH}: track {track}: each filter must be a single"
                    " 'departments' or 'query' mapping"
                )
            key, value = next(iter(entry.items()))
            if key == "departments":
                filters.append({"departments": value})
            elif key == "query":
                filters.append({"searchQuery": value})
            else:
                sys.exit(f"{CONFIG_PATH}: track {track}: unknown filter '{key}'")
        if not filters:
            sys.exit(f"{CONFIG_PATH}: track {track} has no filters")
        track_filters[str(track)] = filters
    return {
        "location": location,
        "local_radius_miles": int(raw.get("local_radius_miles") or 50),
        "seniority_levels": raw.get("seniority_levels") or [],
        "role_types": raw.get("role_types") or [],
        "track_filters": track_filters,
    }


def run_pass(client, cfg: dict, base_state: dict, days: int, label: str) -> tuple[dict, str | None]:
    """One paginated pass. Returns ({requisition_id: summary}, error)."""
    state = {**base_state, "dateFetchedPastNDays": days}
    if cfg["seniority_levels"]:
        state["seniorityLevel"] = cfg["seniority_levels"]
    if cfg["role_types"]:
        state["roleTypes"] = cfg["role_types"]
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

    cfg = load_config()
    client = HiringCafeClient()
    local = client.resolve_location(cfg["location"], radius_miles=cfg["local_radius_miles"])
    remote = client.resolve_location(cfg["location"])
    if not local or not remote:
        sys.exit(f"could not resolve {cfg['location']}")

    variants = [
        ("local", {"locations": [local]}),
        ("remote", {"locations": [remote], "workplaceTypes": ["Remote"]}),
    ]

    jobs: dict[str, tuple[str, dict]] = {}  # id -> (track, summary)
    errors: list[str] = []
    print(f"ingest: window {args.days} days")
    for track, filter_list in cfg["track_filters"].items():
        for base in filter_list:
            for vname, vstate in variants:
                fname = next(iter(base))
                label = f"track {track} / {fname} / {vname}"
                found, err = run_pass(client, cfg, {**base, **vstate}, args.days, label)
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
                " apply_url, track, source, status, posted_date, summary_json,"
                " first_seen_run_id) VALUES (?,?,?,?,?,?,'hiringcafe','seen',?,?,?)",
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
