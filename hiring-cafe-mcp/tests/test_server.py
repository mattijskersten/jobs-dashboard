"""Tests for the pure logic in server.py: dedupe and pagination stitching."""

import pytest

from hiring_cafe_mcp import server
from hiring_cafe_mcp.api import SERVER_PAGE_SIZE


def hit(i: int, title: str = "Engineer", collapse: str | None = None) -> dict:
    return {
        "requisition_id": f"job-{i}",
        "collapse_key": collapse or f"ck-{i}",
        "job_information": {"title": title},
        "v5_processed_job_data": {"core_job_title": title},
        "apply_url": None,
    }


# -- _dedupe -------------------------------------------------------------------


def test_dedupe_collapses_location_variants():
    hits = [hit(1, collapse="ck"), hit(2, collapse="ck"), hit(3, collapse="ck")]
    out = server._dedupe(hits)
    assert len(out) == 1
    rep, count = out[0]
    assert rep["requisition_id"] == "job-1" and count == 3


def test_dedupe_splits_different_titles_in_one_collapse_group():
    hits = [hit(1, "Engineer", "ck"), hit(2, "Designer", "ck"), hit(3, "Engineer", "ck")]
    out = server._dedupe(hits)
    assert [(h["requisition_id"], n) for h, n in out] == [("job-1", 2), ("job-2", 1)]


def test_dedupe_preserves_order_and_passthrough():
    hits = [hit(3), hit(1), hit(2)]
    out = server._dedupe(hits)
    assert [h["requisition_id"] for h, _ in out] == ["job-3", "job-1", "job-2"]
    assert all(n == 1 for _, n in out)


# -- search_jobs pagination stitching -------------------------------------------

TOTAL = 100  # upstream corpus: job-0 … job-99 in fixed pages of SERVER_PAGE_SIZE


class FakeClient:
    def __init__(self):
        self.pages_requested = []

    def search(self, state, page):
        self.pages_requested.append(page)
        hits = [hit(i) for i in range(page * SERVER_PAGE_SIZE,
                                      min((page + 1) * SERVER_PAGE_SIZE, TOTAL))]
        return {
            "ssrHits": hits,
            "ssrTotalCount": TOTAL,
            "ssrIsLastPage": (page + 1) * SERVER_PAGE_SIZE >= TOTAL,
        }

    def resolve_location(self, *a, **kw):  # pragma: no cover
        raise AssertionError("no location in these tests")


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(server, "_client", client)
    return client


def ids(result):
    return [j["id"] for j in result["jobs"]]


def test_first_page(fake_client):
    result = server.search_jobs(query="x", page=1, page_size=20)
    assert ids(result) == [f"job-{i}" for i in range(20)]
    assert result["has_more"] is True
    assert fake_client.pages_requested == [0]


def test_window_spanning_two_server_pages(fake_client):
    result = server.search_jobs(query="x", page=2, page_size=30)
    assert ids(result) == [f"job-{i}" for i in range(30, 60)]
    assert result["has_more"] is True
    assert fake_client.pages_requested == [0, 1]


def test_window_inside_a_later_server_page(fake_client):
    result = server.search_jobs(query="x", page=3, page_size=20)
    assert ids(result) == [f"job-{i}" for i in range(40, 60)]
    assert fake_client.pages_requested == [1]


def test_last_page_has_no_more(fake_client):
    result = server.search_jobs(query="x", page=5, page_size=20)
    assert ids(result) == [f"job-{i}" for i in range(80, 100)]
    assert result["has_more"] is False
    assert result["total_postings"] == TOTAL


def test_page_beyond_end_is_empty(fake_client):
    result = server.search_jobs(query="x", page=6, page_size=20)
    assert ids(result) == []
    assert result["has_more"] is False
