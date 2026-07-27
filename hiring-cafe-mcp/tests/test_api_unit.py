"""Unit tests for transport-layer logic in api.py (no network)."""

import pytest

from hiring_cafe_mcp.api import HiringCafeClient


class FakeResponse:
    """Minimal stand-in for a curl_cffi Response."""

    def __init__(self, status_code=200, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


# -- _is_bot_challenge ---------------------------------------------------------


def test_vercel_checkpoint_is_a_challenge():
    resp = FakeResponse(403, text="... Vercel Security Checkpoint ...")
    assert HiringCafeClient._is_bot_challenge(resp) is True


def test_cloudflare_mitigated_header_is_a_challenge():
    resp = FakeResponse(403, text="", headers={"cf-mitigated": "challenge"})
    assert HiringCafeClient._is_bot_challenge(resp) is True


def test_cloudflare_just_a_moment_title_is_a_challenge():
    resp = FakeResponse(403, text="<html><title>Just a moment...</title>")
    assert HiringCafeClient._is_bot_challenge(resp) is True


def test_plain_403_is_not_a_challenge():
    resp = FakeResponse(403, text="Forbidden", headers={"cf-mitigated": "block"})
    assert HiringCafeClient._is_bot_challenge(resp) is False


# -- _retry_delay --------------------------------------------------------------


def test_retry_delay_honors_retry_after_header():
    resp = FakeResponse(429, headers={"Retry-After": "5"})
    assert HiringCafeClient._retry_delay(resp, attempt=0) == 5.0


def test_retry_delay_falls_back_to_exponential_backoff():
    resp = FakeResponse(429, headers={})
    assert HiringCafeClient._retry_delay(resp, attempt=0) == 1.0
    assert HiringCafeClient._retry_delay(resp, attempt=1) == 2.0
    assert HiringCafeClient._retry_delay(resp, attempt=2) == 4.0


def test_retry_delay_ignores_garbage_retry_after():
    resp = FakeResponse(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    assert HiringCafeClient._retry_delay(resp, attempt=1) == 2.0
