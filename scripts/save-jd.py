#!/usr/bin/env python3
"""Persist a JD whose text is already in hand — verbatim — and set jd_path.

For the LinkedIn triage path: its MCP is external (no in-repo client), so the
model must be the conduit for the fetched text. This makes that a mechanical
pipe rather than an authoring step — pipe the `get_job_details` `description`
field in unchanged; do not summarize, reorder, or add headers. The write and
the DB update are owned here, by jd_store, so LinkedIn lands its JD the same way
every run.

Stdlib only.

Usage (via scripts/save-jd.sh, or directly):

    <get_job_details description> | scripts/save-jd.py --job-id linkedin-<id> --company "<name>"
    scripts/save-jd.py --job-id linkedin-<id> --company "<name>" --file JD.txt
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jd_store  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--job-id", required=True, help="the jobs.job_id to attach the JD to")
    ap.add_argument("--company", required=True, help="company name for the JD filename")
    ap.add_argument("--file", default=None, help="read JD text from this file instead of stdin")
    ap.add_argument("--db", default=str(ROOT / "data" / "jobs.db"))
    args = ap.parse_args()

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    else:
        text = sys.stdin.read()
    text = text.strip()
    if not text:
        sys.exit("no JD text supplied (stdin/--file was empty)")

    db = sqlite3.connect(args.db)
    row = db.execute("SELECT 1 FROM jobs WHERE job_id = ?", (args.job_id,)).fetchone()
    if not row:
        sys.exit(f"no jobs row for job_id {args.job_id!r}")

    with db:
        jd_path = jd_store.write_jd(args.company, args.job_id, text, db)

    print(f"saved JD for {args.job_id} ({len(text)} chars): {jd_path}")


if __name__ == "__main__":
    main()
