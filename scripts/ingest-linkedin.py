#!/usr/bin/env python3
"""Deterministic dedup + insert for LinkedIn collection.

The ~4 paced `search_jobs` calls stay model-driven — they need the browser MCP
session and its pacing — but the model's only job afterwards is to parse each
search's `sections` blob into records and pipe them here as JSON. This script
owns the consequential part (dedup against data/jobs.db and the INSERT) so
LinkedIn lands rows by the same fixed rule every run, the way
scripts/ingest-jobs.py does for hiring.cafe.

Input (stdin): a JSON array of records, each:
    {"id": <int|str>, "title": str, "company": str,
     "location": str|null, "posted": str|null, "track": "A"|"B"}

Only stdlib is used, so any python3 runs it.

Usage:
    scripts/ingest-linkedin.py [--run-id ID] [--db PATH] < records.json
"""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dedup import classify, norm_company, norm_title  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _posted_date(posted):
    """Accept an explicit ISO date only; relative phrases ('2 weeks ago') -> None."""
    m = re.fullmatch(r"\d{4}-\d{2}-\d{2}", (posted or "").strip())
    return m.group(0) if m else None


def _summary(rec, url):
    return {
        "source": "linkedin",
        "linkedin_id": str(rec["id"]),
        "title": rec["title"],
        "company": rec["company"],
        "location": rec.get("location"),
        "posted": rec.get("posted"),
        "url": url,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", type=int, default=None)
    ap.add_argument("--db", default=str(ROOT / "data" / "jobs.db"))
    args = ap.parse_args()

    records = json.load(sys.stdin)
    db = sqlite3.connect(args.db)
    rows = db.execute("SELECT job_id, company, title FROM jobs").fetchall()
    known_ids = {r[0] for r in rows}
    existing = [(norm_company(c), norm_title(t)) for _, c, t in rows]

    inserted, exact, cross = classify(records, known_ids, existing)

    with db:
        for rec in inserted:
            lid = f"linkedin-{rec['id']}"
            url = f"https://www.linkedin.com/jobs/view/{rec['id']}/"
            db.execute(
                "INSERT OR IGNORE INTO jobs (job_id, company, title, url,"
                " apply_url, track, source, status, posted_date, summary_json,"
                " first_seen_run_id) VALUES (?,?,?,?,?,?,'linkedin','seen',?,?,?)",
                (
                    lid,
                    rec["company"],
                    rec["title"],
                    url,
                    url,
                    rec.get("track"),
                    _posted_date(rec.get("posted")),
                    json.dumps(_summary(rec, url), ensure_ascii=False),
                    args.run_id,
                ),
            )

    print(
        f"linkedin ingest: {len(records)} hits, {len(inserted)} inserted as 'seen', "
        f"{len(exact)} exact dup, {len(cross)} cross-source dup"
    )
    for lid, dup in cross:
        print(f"  cross-source skip: {lid} ~ existing {dup[0]!r} / {dup[1]!r}")
    for rec in inserted:
        print(f"  inserted: linkedin-{rec['id']} | {rec.get('track')} | "
              f"{rec['company']} | {rec['title']}")


if __name__ == "__main__":
    main()
