#!/usr/bin/env python3
"""One-time backfill of the jobs.source column from existing summary_json.

The source column was added after rows already existed (its NOT NULL default of
'hiringcafe' makes them non-null but wrong for LinkedIn/manual rows). This maps
each row to its true source, derived from the source marker captured inside
summary_json at ingest time:

    summary_json.source == 'linkedin' -> linkedin
    summary_json.source == 'manual'   -> manual   (also any manual-* job_id)
    everything else (incl. NULL json) -> hiringcafe

Stdlib only — no network. Idempotent: re-running it is a no-op once correct.

    python3 scripts/backfill-source.py
"""

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def source_for(job_id: str, summary_json: str | None) -> str:
    if summary_json:
        try:
            marker = json.loads(summary_json).get("source")
        except (ValueError, TypeError):
            marker = None
        if marker in ("linkedin", "manual"):
            return marker
    # manual JDs derive ids prefixed "manual-" (see ingest-jd.py); trust that
    # even if the summary marker is missing.
    if job_id.startswith("manual-"):
        return "manual"
    return "hiringcafe"


def main() -> None:
    db = sqlite3.connect(ROOT / "data" / "jobs.db")
    rows = db.execute("SELECT job_id, summary_json, source FROM jobs").fetchall()

    changed = 0
    with db:
        for job_id, summary_json, current in rows:
            want = source_for(job_id, summary_json)
            if want != current:
                db.execute(
                    "UPDATE jobs SET source = ?, updated_at = datetime('now')"
                    " WHERE job_id = ?",
                    (want, job_id),
                )
                changed += 1

    counts = dict(db.execute("SELECT source, count(*) FROM jobs GROUP BY source"))
    print(f"updated {changed}/{len(rows)} row(s)")
    print("source distribution:", counts)


if __name__ == "__main__":
    main()
