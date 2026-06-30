"""HTTP client for hiring.cafe's unofficial Next.js data API.

hiring.cafe is a Next.js app whose search and job pages are server-side
rendered. The JSON that powers them is fetched from the ``/_next/data``
routes, which require the current deployment's build id. The build id
changes on every deploy, so it is scraped from the homepage and refreshed
whenever a data route starts returning 404. See API_NOTES.md for the full
endpoint documentation.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any
from urllib.parse import quote

import httpx

BASE_URL = "https://hiring.cafe"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

_BUILD_ID_RE = re.compile(r'"buildId":"([^"]+)"')

# Server-fixed: each search page contains 40 collapse groups (unique jobs).
SERVER_PAGE_SIZE = 40

# Backoff schedule for HTTP 429: retry after 1s, 2s, 4s, then give up.
RATE_LIMIT_RETRIES = 3
RATE_LIMIT_BASE_DELAY = 1.0
RATE_LIMIT_MAX_DELAY = 30.0


class HiringCafeError(Exception):
    """A request to hiring.cafe failed in a way the caller should see."""


class NotFoundError(HiringCafeError):
    """The data route 404'd even with a fresh buildId."""


class BlockedError(HiringCafeError):
    """Vercel's bot protection flagged this client (HTTP 403 checkpoint).

    Temporary and IP-level; triggered by heavy request volume. Back off for
    a while — do not retry in a loop, that extends the block.
    """


class HiringCafeClient:
    def __init__(self, timeout: float = 30.0):
        self._http = httpx.Client(
            base_url=BASE_URL, headers=_BROWSER_HEADERS, timeout=timeout,
            follow_redirects=True,
        )
        self._build_id: str | None = None
        self._lock = threading.Lock()

    def close(self) -> None:
        self._http.close()

    # -- build id ----------------------------------------------------------

    def _fetch_build_id(self) -> str:
        resp = self._request("GET", "/", headers={"Accept": "text/html"})
        m = _BUILD_ID_RE.search(resp.text)
        if not m:
            raise HiringCafeError(
                "Could not find the Next.js buildId on the hiring.cafe "
                "homepage. The site layout may have changed; see API_NOTES.md."
            )
        return m.group(1)

    def _get_build_id(self, force_refresh: bool = False) -> str:
        with self._lock:
            if self._build_id is None or force_refresh:
                self._build_id = self._fetch_build_id()
            return self._build_id

    # -- low-level request handling ----------------------------------------

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            try:
                resp = self._http.request(method, url, **kwargs)
            except httpx.TimeoutException as exc:
                raise HiringCafeError(f"hiring.cafe request timed out: {exc}") from exc
            except httpx.HTTPError as exc:
                raise HiringCafeError(f"Could not reach hiring.cafe: {exc}") from exc
            if resp.status_code != 429:
                break
            if attempt == RATE_LIMIT_RETRIES:
                raise HiringCafeError(
                    "hiring.cafe rate-limited the request (HTTP 429) and kept "
                    f"doing so through {RATE_LIMIT_RETRIES} retries with "
                    "backoff. Wait a minute before trying again."
                )
            time.sleep(self._retry_delay(resp, attempt))
        if resp.status_code == 403 and "Vercel Security Checkpoint" in resp.text:
            raise BlockedError(
                "hiring.cafe's bot protection flagged this client (Vercel "
                "Security Checkpoint, HTTP 403). The block is temporary and "
                "IP-level — stop making requests and retry in 15–60 minutes. "
                "Pace bulk calls at 1/s to avoid this."
            )
        if resp.status_code >= 500:
            raise HiringCafeError(
                f"hiring.cafe returned a server error (HTTP {resp.status_code}). "
                "The unofficial API may be temporarily down; retry later."
            )
        return resp

    @staticmethod
    def _retry_delay(resp: httpx.Response, attempt: int) -> float:
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return min(max(float(retry_after), 0.0), RATE_LIMIT_MAX_DELAY)
            except ValueError:
                pass  # HTTP-date form (or garbage); fall back to backoff
        return min(RATE_LIMIT_BASE_DELAY * 2**attempt, RATE_LIMIT_MAX_DELAY)

    def _data_route(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        """GET a /_next/data route, re-resolving the buildId once on 404."""
        for attempt in (0, 1):
            build_id = self._get_build_id(force_refresh=attempt > 0)
            resp = self._request(
                "GET", f"/_next/data/{build_id}{path}", params=params,
                headers={"x-nextjs-data": "1"},
            )
            if resp.status_code == 404 and attempt == 0:
                continue  # stale buildId after a site deploy
            if resp.status_code == 404:
                raise NotFoundError(
                    f"hiring.cafe returned 404 for {path} even with a fresh "
                    "buildId. The resource does not exist or the data-route "
                    "scheme changed (see API_NOTES.md)."
                )
            if resp.status_code != 200:
                raise HiringCafeError(
                    f"Unexpected HTTP {resp.status_code} from hiring.cafe "
                    f"for {path}."
                )
            try:
                return resp.json()["pageProps"]
            except (json.JSONDecodeError, KeyError) as exc:
                raise HiringCafeError(
                    "hiring.cafe returned a response without the expected "
                    "'pageProps' JSON — the unofficial API shape has changed."
                ) from exc
        raise AssertionError("unreachable")

    # -- public API ---------------------------------------------------------

    def search(self, search_state: dict[str, Any], server_page: int) -> dict[str, Any]:
        """One server page of search results (40 unique jobs).

        Returns the pageProps dict with ssrHits / ssrTotalCount /
        ssrIsLastPage etc.
        """
        props = self._data_route(
            "/index.json",
            {"searchState": json.dumps(search_state), "page": str(server_page)},
        )
        if props.get("ssrError"):
            raise HiringCafeError(f"hiring.cafe search failed: {props['ssrError']}")
        if "ssrHits" not in props:
            raise HiringCafeError(
                "hiring.cafe search response is missing 'ssrHits' — the "
                "unofficial API shape has changed (see API_NOTES.md)."
            )
        return props

    def get_job(self, requisition_id: str) -> dict[str, Any]:
        """Full job document (metadata + HTML description) by requisition id."""
        try:
            props = self._data_route(
                f"/job/{quote(requisition_id, safe='')}.json",
                {"requisitionId": requisition_id},
            )
            # hiring.cafe now serves SEO-slug job URLs: the bare-id data route
            # 308-redirects to /job/<slug>-<id>. Next.js reports this as an
            # __N_REDIRECT inside pageProps (HTTP 200, no `job`) rather than a
            # real redirect, so follow it to the slug data route, which carries
            # the actual job document.
            redirect = props.get("__N_REDIRECT")
            if redirect and "job" not in props:
                slug = redirect.rsplit("/job/", 1)[-1].split("?", 1)[0]
                props = self._data_route(
                    f"/job/{quote(slug, safe='')}.json",
                    {"requisitionId": requisition_id},
                )
        except NotFoundError:
            props = {}
        job = props.get("job")
        if not job:
            raise HiringCafeError(
                f"No job found for id '{requisition_id}'. The posting may have "
                "been removed, or the id is not a hiring.cafe job id from "
                "search_jobs results."
            )
        return job

    def resolve_location(
        self, query: str, radius_miles: int | None = None
    ) -> dict[str, Any] | None:
        """Resolve a free-text location to hiring.cafe's place object.

        Returns the top suggestion's placeDetail, or None if nothing matched.
        With ``radius_miles``, the place filters like the website's radius
        option (local jobs only); without it, remote jobs hirable from the
        place's continent or anywhere are included too.
        """
        resp = self._request("GET", "/api/searchLocation", params={"query": query})
        if resp.status_code != 200:
            raise HiringCafeError(
                f"Location lookup failed (HTTP {resp.status_code})."
            )
        try:
            suggestions = resp.json()
        except json.JSONDecodeError as exc:
            raise HiringCafeError("Location lookup returned invalid JSON.") from exc
        if not suggestions:
            return None
        place = suggestions[0].get("placeDetail")
        if not place:
            return None
        # The search rejects extra fields (e.g. `population`), so send only
        # what the site itself puts into searchState.locations.
        trimmed = {
            k: place[k]
            for k in ("id", "types", "address_components", "geometry",
                      "formatted_address")
            if k in place
        }
        if radius_miles is not None:
            # The website's radius filter: local jobs only.
            trimmed["options"] = {
                "radius": radius_miles,
                "radius_unit": "miles",
                "ignore_radius": False,
            }
        else:
            # Matches the site default: also surface remote jobs hirable from
            # this place's wider region.
            trimmed["options"] = {
                "flexible_regions": ["anywhere_in_continent", "anywhere_in_world"]
            }
        return trimmed
