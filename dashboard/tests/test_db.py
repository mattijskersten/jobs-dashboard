"""Tests for the dashboard's DB layer: status transitions and path safety."""

import sqlite3
from pathlib import Path

import pytest

from jobs_dashboard import db

SCHEMA = Path(__file__).resolve().parents[2] / "scripts" / "schema.sql"


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A throwaway repo root with a schema-fresh data/jobs.db."""
    (tmp_path / "data" / "jds").mkdir(parents=True)
    conn = sqlite3.connect(tmp_path / "data" / "jobs.db")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executemany(
        "INSERT INTO jobs (job_id, company, title, status) VALUES (?,?,?,?)",
        [
            ("review-1", "Acme", "Head of Product", "needs-review"),
            ("short-1", "Globex", "CIO", "shortlisted"),
            ("tail-1", "Initech", "VP Product", "tailored"),
            ("rej-1", "Hooli", "PM", "rejected"),
        ],
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("JOBS_DASHBOARD_ROOT", str(tmp_path))
    return tmp_path


def status_of(job_id):
    return db.get_job(job_id)["status"]


def test_promote_from_needs_review(root):
    changed, _ = db.apply_action("review-1", "promote")
    assert changed and status_of("review-1") == "shortlisted"


def test_promote_refused_outside_needs_review(root):
    for job_id in ("short-1", "tail-1", "rej-1"):
        changed, message = db.apply_action(job_id, "promote")
        assert not changed and "promote" in message


def test_reject_reopen_roundtrip(root):
    changed, _ = db.apply_action("short-1", "reject")
    assert changed and status_of("short-1") == "rejected"
    changed, _ = db.apply_action("short-1", "reopen")
    assert changed and status_of("short-1") == "needs-review"


def test_applied_only_from_tailored(root):
    changed, _ = db.apply_action("tail-1", "applied")
    assert changed and status_of("tail-1") == "applied"
    changed, _ = db.apply_action("review-1", "applied")
    assert not changed and status_of("review-1") == "needs-review"


def test_unknown_action_refused(root):
    changed, message = db.apply_action("review-1", "nuke")
    assert not changed and "unknown action" in message


def test_missing_job_refused(root):
    changed, _ = db.apply_action("no-such-job", "promote")
    assert not changed


def test_actions_only_target_valid_statuses(root):
    # every status named in ACTIONS must be a real funnel status
    valid = set(db.STATUS_ORDER)
    for new_status, allowed_from in db.ACTIONS.values():
        assert new_status in valid
        assert allowed_from <= valid


def test_toggle_star(root):
    assert db.toggle_star("review-1") is True
    assert db.get_job("review-1")["starred"] == 1
    assert db.toggle_star("review-1") is False
    assert db.toggle_star("no-such-job") is False


def test_safe_data_path_accepts_files_inside_data(root):
    jd = root / "data" / "jds" / "JD Acme x.txt"
    jd.write_text("desc", encoding="utf-8")
    assert db.safe_data_path("data/jds/JD Acme x.txt") == jd.resolve()


def test_safe_data_path_rejects_escapes(root):
    (root / "secret.txt").write_text("s", encoding="utf-8")
    assert db.safe_data_path("data/../secret.txt") is None
    assert db.safe_data_path("../../etc/passwd") is None
    assert db.safe_data_path("/etc/passwd") is None


def test_safe_data_path_missing_or_empty(root):
    assert db.safe_data_path("data/jds/nope.txt") is None
    assert db.safe_data_path(None) is None
    assert db.safe_data_path("") is None
