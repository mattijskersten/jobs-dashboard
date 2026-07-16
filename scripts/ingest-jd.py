#!/usr/bin/env python3
"""Land a manually-provided job description in data/jobs.db as a `seen` row.

Search hits arrive without a description and get one fetched at triage time;
a manual JD already *is* the description, so this script just saves it to disk
and inserts a `seen` row whose jd_path points at it. From there it flows
through the normal funnel — triage scores it, tailoring reads the JD from
disk — exactly like a hiring.cafe job, but with no hiring.cafe id and nothing
to fetch online.

Usage (via scripts/ingest-jd.sh):

    scripts/ingest-jd.sh --file PATH --company NAME --title TITLE \
        [--url URL] [--apply-url URL] [--location TEXT] \
        [--workplace-type Remote|Hybrid|Onsite] [--posted-date YYYY-MM-DD] \
        [--track A|B] [--run-id ID]

The job id is derived from company + title, so re-ingesting the same role
(e.g. after editing the JD text) refreshes it in place rather than duplicating.
Stdlib only — no hiring.cafe API call is made.
"""

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import jd_store  # scripts/jd_store.py — the one JD-file + naming convention

ROOT = Path(__file__).resolve().parent.parent
SUMMARY_EXCERPT_CHARS = 1500


def derive_id(company: str, title: str) -> str:
    norm = f"{company.strip().lower()}|{title.strip().lower()}"
    return "manual-" + hashlib.sha1(norm.encode()).hexdigest()[:10]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="path to the JD text/markdown file")
    ap.add_argument("--company", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--url", default=None, help="job posting URL")
    ap.add_argument("--apply-url", default=None, help="application link (company/ATS portal)")
    ap.add_argument("--location", default=None, help="e.g. 'Remote (EU)' or 'Your City, Country'")
    ap.add_argument("--workplace-type", default=None, help="Remote | Hybrid | Onsite")
    ap.add_argument("--posted-date", default=None, help="YYYY-MM-DD if known")
    ap.add_argument("--track", choices=["A", "B"], default=None)
    ap.add_argument("--run-id", type=int, default=None)
    args = ap.parse_args()

    src = Path(args.file)
    if not src.is_file():
        sys.exit(f"JD file not found: {src}")
    text = src.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        sys.exit(f"JD file is empty: {src}")

    job_id = derive_id(args.company, args.title)
    # jd_store owns the file + naming convention; this script sets jd_path
    # itself as part of its own INSERT/UPDATE below, so pass no db handle.
    jd_path = jd_store.write_jd(args.company, job_id, text)

    summary = {
        "id": job_id,
        "source": "manual",
        "company": args.company,
        "title": args.title,
        "url": args.url,
        "apply_url": args.apply_url,
        "location": args.location,
        "workplace_type": args.workplace_type,
        "posted": args.posted_date,
        "jd_on_disk": jd_path,
        "jd_chars": len(text),
        "requirements_summary": text[:SUMMARY_EXCERPT_CHARS],
    }

    db = sqlite3.connect(ROOT / "data" / "jobs.db")
    existing = db.execute(
        "SELECT status FROM jobs WHERE job_id = ?", (job_id,)
    ).fetchone()

    with db:
        if existing:
            # Already in the funnel: refresh the stored JD + summary in place,
            # but never regress a triaged/tailored row back to 'seen'.
            db.execute(
                "UPDATE jobs SET summary_json = ?, jd_path = ?, apply_url = COALESCE(?, apply_url),"
                " url = COALESCE(?, url), posted_date = COALESCE(?, posted_date),"
                " updated_at = datetime('now') WHERE job_id = ?",
                (json.dumps(summary, ensure_ascii=False), jd_path, args.apply_url,
                 args.url, args.posted_date, job_id),
            )
        else:
            db.execute(
                "INSERT INTO jobs (job_id, company, title, url, apply_url, track,"
                " source, status, posted_date, summary_json, jd_path, first_seen_run_id)"
                " VALUES (?,?,?,?,?,?,'manual','seen',?,?,?,?)",
                (job_id, args.company, args.title, args.url, args.apply_url,
                 args.track, args.posted_date, json.dumps(summary, ensure_ascii=False),
                 jd_path, args.run_id),
            )

    if existing:
        print(f"refreshed {job_id} ({args.company} — {args.title}); "
              f"already in funnel at status '{existing[0]}'. JD: {jd_path}")
    else:
        print(f"ingested {job_id} ({args.company} — {args.title}) as 'seen'. JD: {jd_path}")


if __name__ == "__main__":
    main()
