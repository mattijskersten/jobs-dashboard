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


def test_close_from_tailored_and_reopen_restores_tailored(root):
    # tail-1 has a CV on file, so reopening a closed job restores 'tailored'
    with sqlite3.connect(root / "data" / "jobs.db") as conn:
        conn.execute(
            "UPDATE jobs SET cv_pdf_path = 'data/cvs/cv X Initech.pdf'"
            " WHERE job_id = 'tail-1'"
        )
    changed, _ = db.apply_action("tail-1", "close")
    assert changed and status_of("tail-1") == "closed"
    changed, message = db.apply_action("tail-1", "reopen")
    assert changed and status_of("tail-1") == "tailored"
    assert "tailored" in message


def test_close_and_reopen_without_cv_goes_to_needs_review(root):
    changed, _ = db.apply_action("short-1", "close")
    assert changed and status_of("short-1") == "closed"
    changed, _ = db.apply_action("short-1", "reopen")
    assert changed and status_of("short-1") == "needs-review"


def test_close_refused_from_applied_and_rejected(root):
    # an applied job is never 'closed' — the posting didn't retire on me, so if
    # it's dead it's because the company declined (see test_decline_*)
    db.apply_action("tail-1", "applied")
    for job_id in ("tail-1", "rej-1"):
        changed, _ = db.apply_action(job_id, "close")
        assert not changed


def test_decline_from_applied(root):
    db.apply_action("tail-1", "applied")
    changed, _ = db.apply_action("tail-1", "decline")
    assert changed and status_of("tail-1") == "declined"


def test_decline_refused_outside_applied(root):
    db.apply_action("short-1", "close")
    for job_id in ("review-1", "tail-1", "short-1", "rej-1"):
        changed, message = db.apply_action(job_id, "decline")
        assert not changed and "decline" in message


def test_declined_is_terminal(root):
    # the company said no after I applied — there's no earlier stage to reopen
    # to, so 'declined' accepts no further transitions
    db.apply_action("tail-1", "applied")
    db.apply_action("tail-1", "decline")
    for action in db.ACTIONS:
        changed, _ = db.apply_action("tail-1", action)
        assert not changed, f"{action} escaped the terminal 'declined' state"
    assert status_of("tail-1") == "declined"


def test_reopen_from_rejected_still_goes_to_needs_review(root):
    # a rejected job with a CV path must NOT reopen to tailored — the
    # tailored-restore shortcut is for closed jobs only
    with sqlite3.connect(root / "data" / "jobs.db") as conn:
        conn.execute(
            "UPDATE jobs SET cv_pdf_path = 'data/cvs/cv X Hooli.pdf'"
            " WHERE job_id = 'rej-1'"
        )
    changed, _ = db.apply_action("rej-1", "reopen")
    assert changed and status_of("rej-1") == "needs-review"


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
