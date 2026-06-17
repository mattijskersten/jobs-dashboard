#!/usr/bin/env python3
"""Backfill jobs columns (posted_date, apply_url) from hiring.cafe.

Fetches details once per row that is missing any of the backfillable fields.
Run from the repo root with the MCP server's venv (it has httpx):

    hiring-cafe-mcp/.venv/bin/python3 scripts/backfill-job-fields.py [--all]

By default only non-rejected rows are filled; --all includes rejects.
Calls are paced at 1/s to stay clear of hiring.cafe rate limits — the API
is unofficial, so be a polite guest.
"""

import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hiring-cafe-mcp" / "src"))

from hiring_cafe_mcp.api import (  # noqa: E402
    BlockedError,
    HiringCafeClient,
    HiringCafeError,
)


def fields_from_job(hit: dict) -> dict[str, str | None]:
    """Map a hiring.cafe job document to the backfillable jobs columns."""
    v5 = hit.get("v5_processed_job_data") or {}
    return {
        "posted_date": (v5.get("estimated_publish_date") or "")[:10] or None,
        "apply_url": hit.get("apply_url"),
    }


def main() -> None:
    include_rejected = "--all" in sys.argv[1:]
    where = "(posted_date IS NULL OR apply_url IS NULL)"
    if not include_rejected:
        where += " AND status != 'rejected'"

    client = HiringCafeClient()
    db = sqlite3.connect(ROOT / "data" / "jobs.db")
    rows = db.execute(
        f"SELECT job_id, company FROM jobs WHERE {where}"
    ).fetchall()
    print(f"{len(rows)} row(s) to backfill")

    filled = gone = 0
    for job_id, company in rows:
        time.sleep(1)  # pace every call; unofficial API, avoid rate limits
        try:
            hit = client.get_job(job_id)
        except BlockedError as exc:
            print(f"ABORT (do not retry in a loop): {exc}")
            break
        except HiringCafeError as exc:
            if "No job found" in str(exc):
                gone += 1
                print(f"  gone from hiring.cafe: {company} ({job_id})")
                continue
            # Transport/API errors are not "job gone" — stop rather than
            # burn a request per remaining row.
            print(f"ABORT on API error: {exc}")
            break
        updates = {k: v for k, v in fields_from_job(hit).items() if v}
        if updates:
            sets = ", ".join(f"{k} = ?" for k in updates)
            db.execute(
                f"UPDATE jobs SET {sets}, updated_at = datetime('now')"
                " WHERE job_id = ? AND ("
                + " OR ".join(f"{k} IS NULL" for k in updates)
                + ")",
                (*updates.values(), job_id),
            )
            filled += 1
    db.commit()
    print(f"backfilled {filled}/{len(rows)}; {gone} no longer live")


if __name__ == "__main__":
    main()
