"""SQLite access for the dashboard: read queries + guarded status writes.

The database is the same data/jobs.db the pipeline writes. We resolve the repo
root from this file's location (dashboard/src/jobs_dashboard/db.py -> repo root),
overridable with JOBS_DASHBOARD_ROOT so the app can run from a worktree or point
at another checkout. All writes are short, status-guarded transactions in the
same spirit as scripts/promote.sh — we never blindly overwrite a status.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

# Active funnel statuses, in the order a job moves through them. (The schema
# CHECK also still accepts a legacy 'triaged' value nothing writes anymore.)
# 'rejected' = I judged it a bad fit; 'closed' = the posting was retired
# before I could apply — kept distinct so closed jobs don't pollute the
# rejected bucket when reviewing triage quality.
STATUS_ORDER = [
    "seen", "needs-review", "shortlisted", "tailored", "applied",
    "rejected", "closed",
]

# action -> (new_status, {statuses it may be applied from})
# Canonical transition table; scripts/promote.sh mirrors these rules for the
# CLI (promote/reject/close) — keep them in sync. Note: reopening a closed
# job that already has a tailored CV restores 'tailored', not 'needs-review'
# (special-cased in apply_action).
ACTIONS: dict[str, tuple[str, set[str]]] = {
    "promote": ("shortlisted", {"needs-review"}),
    "reject": ("rejected", {"needs-review", "shortlisted", "seen"}),
    "close": ("closed", {"needs-review", "shortlisted", "tailored"}),
    "reopen": ("needs-review", {"rejected", "closed"}),
    "applied": ("applied", {"tailored"}),
}


def repo_root() -> Path:
    env = os.environ.get("JOBS_DASHBOARD_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[3]


def data_dir() -> Path:
    return repo_root() / "data"


def db_path() -> Path:
    return data_dir() / "jobs.db"


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _job_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    job = dict(row)
    summary = None
    if job.get("summary_json"):
        try:
            summary = json.loads(job["summary_json"])
        except (ValueError, TypeError):
            summary = None
    job["summary"] = summary
    return job


def overview() -> dict[str, Any]:
    """Funnel counts by status and by source, plus recent runs."""
    with connect() as conn:
        status_counts = {
            r["status"]: r["n"]
            for r in conn.execute("SELECT status, count(*) n FROM jobs GROUP BY status")
        }
        source_counts = {
            r["source"]: r["n"]
            for r in conn.execute("SELECT source, count(*) n FROM jobs GROUP BY source")
        }
        starred = conn.execute("SELECT count(*) FROM jobs WHERE starred = 1").fetchone()[0]
        runs = [
            dict(r)
            for r in conn.execute(
                "SELECT run_id, started_at, finished_at, jobs_seen, shortlisted,"
                " needs_review, rejected, tailored, errors, report_path FROM runs"
                " ORDER BY run_id DESC LIMIT 10"
            )
        ]
    ordered = {s: status_counts.get(s, 0) for s in STATUS_ORDER if status_counts.get(s)}
    return {
        "status_counts": ordered,
        "total": sum(status_counts.values()),
        "source_counts": source_counts,
        "starred": starred,
        "runs": runs,
    }


def list_jobs(
    status: str | None = None,
    source: str | None = None,
    track: str | None = None,
    min_score: int | None = None,
    starred: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if status:
        # comma-separated set of statuses
        wanted = [s for s in status.split(",") if s]
        where.append("status IN (%s)" % ",".join("?" * len(wanted)))
        params.extend(wanted)
    if source:
        where.append("source = ?")
        params.append(source)
    if track:
        where.append("track = ?")
        params.append(track)
    if min_score is not None:
        where.append("score >= ?")
        params.append(min_score)
    if starred:
        where.append("starred = 1")
    sql = "SELECT * FROM jobs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    # Starred always float to the top; then highest score, then most recently
    # touched; NULL scores last.
    sql += " ORDER BY starred DESC, score IS NULL, score DESC, updated_at DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    with connect() as conn:
        return [_job_to_dict(r) for r in conn.execute(sql, params)]


def get_job(job_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    return _job_to_dict(row) if row else None


def get_run(run_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def apply_action(job_id: str, action: str) -> tuple[bool, str]:
    """Apply a named status transition, guarded by the allowed source statuses.

    Returns (changed, message). changed is False if the job wasn't in a state
    the action permits (so a stale page can't force an illegal transition).
    """
    if action not in ACTIONS:
        return False, f"unknown action: {action}"
    new_status, allowed_from = ACTIONS[action]
    # Reopening a closed job that already carries a tailored CV puts it back
    # where it was (tailored), not at the review stage — the CV still exists.
    set_expr = "?"
    if action == "reopen":
        set_expr = (
            "CASE WHEN status = 'closed' AND cv_pdf_path IS NOT NULL"
            " THEN 'tailored' ELSE ? END"
        )
    placeholders = ",".join("?" * len(allowed_from))
    with connect() as conn:
        cur = conn.execute(
            f"UPDATE jobs SET status = {set_expr}, updated_at = datetime('now')"
            f" WHERE job_id = ? AND status IN ({placeholders})",
            (new_status, job_id, *sorted(allowed_from)),
        )
        conn.commit()
        changed = cur.rowcount > 0
        if changed:
            row = conn.execute(
                "SELECT status FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            return True, f"{action} → {row['status']}"
    return False, f"job not in a state that allows '{action}'"


def toggle_star(job_id: str) -> bool:
    """Flip a job's starred flag. Returns the new state (True = starred)."""
    with connect() as conn:
        cur = conn.execute(
            "UPDATE jobs SET starred = 1 - starred, updated_at = datetime('now')"
            " WHERE job_id = ?",
            (job_id,),
        )
        conn.commit()
        if cur.rowcount == 0:
            return False
        row = conn.execute(
            "SELECT starred FROM jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
    return bool(row["starred"])


def safe_data_path(stored: str | None) -> Path | None:
    """Resolve a DB-stored relative path and confirm it stays inside data/.

    Stored paths look like 'data/jds/JD Foo abc.txt' or
    'data/cvs/cv Name Foo.pdf' — relative to the repo root. Reject anything that
    escapes the data directory.
    """
    if not stored:
        return None
    root = repo_root()
    candidate = (root / stored).resolve()
    ddir = data_dir().resolve()
    if ddir == candidate or ddir in candidate.parents:
        return candidate if candidate.is_file() else None
    return None
