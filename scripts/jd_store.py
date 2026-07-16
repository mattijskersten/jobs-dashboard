#!/usr/bin/env python3
"""The one place a job description is persisted to disk.

Every source's full JD lands here verbatim — the mechanical "write the fetched
text, point the row at it" step, kept out of the model's hands so the on-disk JD
is the source text and not a paraphrase. Callers: scripts/fetch-jd.py
(hiring.cafe), scripts/save-jd.py (LinkedIn), scripts/ingest-jd.py (manual). The
filename convention lives once, here, on top of scripts/sanitize.safe_label.

Stdlib only, so any python3 imports it.
"""

import sqlite3
from pathlib import Path

from sanitize import safe_label  # scripts/sanitize.py — shared filename convention

ROOT = Path(__file__).resolve().parent.parent
JD_DIR = ROOT / "data" / "jds"


def jd_filename(company: str, job_id: str) -> str:
    """`JD <company> <job_id>.txt` — the shared JD-file naming convention."""
    return f"JD {safe_label(company)} {job_id}.txt"


def write_jd(company: str, job_id: str, text: str, db: sqlite3.Connection | None = None) -> str:
    """Write `text` verbatim to data/jds/ and set the row's jd_path.

    Returns the repo-relative jd_path. When `db` is given the jobs row for
    `job_id` is updated in place (caller owns the transaction/commit); pass
    None to only write the file (e.g. ingest-jd.py, which sets jd_path itself
    as part of its own INSERT/UPDATE).
    """
    JD_DIR.mkdir(parents=True, exist_ok=True)
    jd_file = JD_DIR / jd_filename(company, job_id)
    jd_file.write_text(text, encoding="utf-8")
    jd_path = str(jd_file.relative_to(ROOT))
    if db is not None:
        db.execute(
            "UPDATE jobs SET jd_path = ?, updated_at = datetime('now') WHERE job_id = ?",
            (jd_path, job_id),
        )
    return jd_path
