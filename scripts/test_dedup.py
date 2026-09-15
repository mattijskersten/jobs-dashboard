"""Tests for the LinkedIn dedup logic (scripts/dedup.py) and the ingest script.

Fixtures mirror the shapes seen in a real run, with fictional companies:
Northwind (exact id dup), Fabrikam (cross-source fuzzy dup), Contoso Cloud and Tailspin
(genuine survivors). They pin the normalization rules and the 0.6 threshold so a
future edit that would silently start merging or splitting jobs fails loudly.
"""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dedup  # noqa: E402

SCRIPT = Path(__file__).resolve().parent / "ingest-linkedin.py"
SCHEMA = Path(__file__).resolve().parent / "schema.sql"


# -- norm_company --------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Fabrikam", "fabrikam"),
    ("Contoso Cloud", "contoso cloud"),
    ("Foo Inc", "foo"),
    ("Bar Sp. z o.o.", "bar"),
    ("Baz Co Ltd", "baz"),          # two trailing suffix tokens
    ("Acme GmbH", "acme"),
    ("  Northwind  ", "northwind"),
])
def test_norm_company(raw, expected):
    assert dedup.norm_company(raw) == expected


# -- norm_title ----------------------------------------------------------------

def test_norm_title_drops_mode_geo_and_gender_tags():
    assert dedup.norm_title(
        "Director of Product Management – Data Platform (f/m/x)"
    ) == "director of product management data platform"
    assert dedup.norm_title("Head of Product (Remote, EMEA)") == "head of product"


# -- title_sim -----------------------------------------------------------------

def test_title_sim_is_order_insensitive_and_bounded():
    assert dedup.title_sim("director of product", "product of director") == 1.0
    assert dedup.title_sim("", "anything") == 0.0
    # CPO vs CTO at ~0.5 must sit below the 0.6 gate.
    assert dedup.title_sim(
        "chief product officer", "chief technology officer"
    ) == pytest.approx(0.5)


# -- find_cross_source_dup -----------------------------------------------------

def _existing(pairs):
    return [(dedup.norm_company(c), dedup.norm_title(t)) for c, t in pairs]


def test_cross_source_matches_fabrikam_across_punctuation():
    existing = _existing([
        ("Fabrikam", "Director of Product Management - Data Platform"),
    ])
    hit = dedup.find_cross_source_dup(
        "Fabrikam", "Director of Product Management – Data Platform (f/m/x)",
        existing,
    )
    assert hit is not None


def test_cross_source_requires_same_company():
    existing = _existing([("Northwind", "VP Product")])
    # Same normalized title, different company -> not a dup.
    assert dedup.find_cross_source_dup("Globex", "VP Product", existing) is None


def test_cross_source_keeps_distinct_roles_at_same_company():
    existing = _existing([("Acme", "Chief Product Officer")])
    # Same company, but 0.5 similarity is below threshold -> distinct role.
    assert dedup.find_cross_source_dup(
        "Acme", "Chief Technology Officer", existing
    ) is None


def test_cross_source_survivor_unknown_company():
    existing = _existing([("Fabrikam", "Director of Product Management")])
    assert dedup.find_cross_source_dup(
        "Contoso Cloud", "VP of Product - B2B SaaS scale-up", existing
    ) is None


# -- classify (bucketing + within-batch dedup) ---------------------------------

def test_classify_buckets_the_run_fixtures():
    known_ids = {"linkedin-1000000001"}                       # Northwind seen
    existing = _existing([
        ("Northwind", "VP Product"),
        ("Fabrikam", "Director of Product Management - Data Platform"),
    ])
    records = [
        {"id": 1000000001, "company": "Northwind", "title": "VP Product"},
        {"id": 1000000002, "company": "Contoso Cloud",
         "title": "VP of Product - B2B SaaS scale-up | Europe"},
        {"id": 1000000003, "company": "Fabrikam",
         "title": "Director of Product Management – Data Platform (f/m/x)"},
        {"id": 1000000004, "company": "Tailspin Recruitment",
         "title": "Director of IT & Analytics"},
    ]
    inserted, exact, cross = dedup.classify(records, known_ids, existing)
    assert exact == ["linkedin-1000000001"]
    assert [c[0] for c in cross] == ["linkedin-1000000003"]
    assert {r["id"] for r in inserted} == {1000000002, 1000000004}


def test_classify_dedups_within_batch():
    # Same job returned by two searches -> inserted once, second is an exact dup.
    records = [
        {"id": 111, "company": "Acme", "title": "VP Product"},
        {"id": 111, "company": "Acme", "title": "VP Product"},
    ]
    inserted, exact, cross = dedup.classify(records, set(), [])
    assert len(inserted) == 1 and exact == ["linkedin-111"] and cross == []


# -- end-to-end through the script (proves SQL + schema) -----------------------

@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "jobs.db"
    conn = sqlite3.connect(p)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executemany(
        "INSERT INTO jobs (job_id, company, title, source, status) VALUES (?,?,?,?,?)",
        [
            ("linkedin-1000000001", "Northwind", "VP Product", "linkedin", "seen"),
            ("hiringcafe-fabrikam", "Fabrikam",
             "Director of Product Management - Data Platform",
             "hiringcafe", "seen"),
        ],
    )
    conn.commit()
    conn.close()
    return p


def test_script_inserts_only_survivors(db_path):
    records = [
        {"id": 1000000001, "company": "Northwind", "title": "VP Product",
         "location": "EU (Remote)", "posted": "Viewed", "track": "A"},
        {"id": 1000000002, "company": "Contoso Cloud",
         "title": "VP of Product - B2B SaaS scale-up", "location": "EU (Remote)",
         "posted": "13 hours ago", "track": "A"},
        {"id": 1000000003, "company": "Fabrikam",
         "title": "Director of Product Management – Data Platform (f/m/x)",
         "location": "EMEA (Remote)", "posted": "5 days ago", "track": "A"},
        {"id": 1000000004, "company": "Tailspin Recruitment",
         "title": "Director of IT & Analytics",
         "location": "EU (Remote)", "posted": "2026-07-03", "track": "B"},
    ]
    out = subprocess.run(
        [sys.executable, str(SCRIPT), "--db", str(db_path)],
        input=json.dumps(records), capture_output=True, text=True, check=True,
    )
    assert "2 inserted as 'seen'" in out.stdout
    assert "1 exact dup" in out.stdout and "1 cross-source dup" in out.stdout

    conn = sqlite3.connect(db_path)
    got = dict(conn.execute(
        "SELECT job_id, track FROM jobs WHERE source='linkedin' AND job_id LIKE 'linkedin-10%'"
        " AND job_id NOT IN ('linkedin-1000000001')"
    ).fetchall())
    # Survivors landed with their track; ISO posted date stored, relative left NULL.
    assert got == {"linkedin-1000000002": "A", "linkedin-1000000004": "B"}
    pd = dict(conn.execute(
        "SELECT job_id, posted_date FROM jobs WHERE job_id IN"
        " ('linkedin-1000000002','linkedin-1000000004')"
    ).fetchall())
    assert pd["linkedin-1000000004"] == "2026-07-03"
    assert pd["linkedin-1000000002"] is None
    conn.close()
