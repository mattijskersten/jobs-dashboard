#!/usr/bin/env python3
"""Deterministically fetch one hiring.cafe job's full details and persist its
raw JD.

Triage used to call the `get_job_details` MCP tool and then hand-write the JD
to disk — the model curated the text, so the on-disk JD drifted from the source.
This script owns the consequential part instead: it fetches with the in-repo
client, writes the *verbatim* description to data/jds/ and sets the row's
jd_path, then prints only the compact structured fields for scoring. The long
description never returns to the model — it goes straight to disk (read the
saved file if the prose is needed to score).

Usage (via scripts/fetch-jd.sh, which supplies the MCP server's interpreter):

    scripts/fetch-jd.sh <job_id> --company "<name>" [--db PATH]

--company  used only for the JD filename (JD <company> <job_id>.txt); falls
           back to the company the API reports if omitted.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hiring-cafe-mcp" / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from hiring_cafe_mcp.api import HiringCafeClient, HiringCafeError  # noqa: E402
from hiring_cafe_mcp.server import _job_details  # noqa: E402

import jd_store  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id", help="hiring.cafe requisition id from search")
    ap.add_argument("--company", default=None, help="company name for the JD filename")
    ap.add_argument("--db", default=str(ROOT / "data" / "jobs.db"))
    args = ap.parse_args()

    try:
        hit = HiringCafeClient().get_job(args.job_id)
    except HiringCafeError as exc:
        sys.exit(f"fetch failed for {args.job_id}: {exc}")

    details = _job_details(hit)
    company = args.company or details.get("company") or "(unknown)"
    description = details.pop("description", "") or "(no description available)"

    db = sqlite3.connect(args.db)
    with db:
        jd_path = jd_store.write_jd(company, args.job_id, description, db)

    # Everything the model needs to score, minus the long description (on disk).
    details["jd_path"] = jd_path
    details["jd_note"] = f"full JD saved verbatim to {jd_path}; read it if the prose is needed to score"
    print(json.dumps(details, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
