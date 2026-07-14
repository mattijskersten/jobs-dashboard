# hiring.cafe unofficial API notes

> **Domain migration (2026-07-15):** the site moved from `hiring.cafe` to
> `hiringcafe.com`. The old domain still serves the homepage HTML with a valid
> `buildId`, but its `/_next/data` routes now return the app-shell HTML instead
> of JSON — so `pageProps` extraction fails on every pass. `BASE_URL` in
> `api.py` now points at `hiringcafe.com`. If data routes start returning HTML
> again, check whether the canonical domain moved (the homepage `<link
> rel="canonical">` shows the current one). The `buildId` and data-route scheme
> are unchanged across the move. URLs below still say `hiring.cafe`; read them
> as `hiringcafe.com`.


Discovered 2026-06-12 by inspecting the site's JS bundles and network
behavior. hiring.cafe is a Next.js app; search and job pages are SSR'd, and
their JSON comes from `/_next/data/` routes. There is **no public API and no
stability guarantee** — when the server breaks, start here.

No authentication is needed. A browser-like `User-Agent` header is sent to
be safe.

## Build id (required by all data routes)

`/_next/data/{buildId}/...` routes 404 unless `{buildId}` matches the current
deployment. It is scraped from the homepage HTML:

```
GET https://hiring.cafe/
→ ..."buildId":"FVf1IR-TcysIb8PGlkRwI"...   (regex: "buildId":"([^"]+)")
```

The client caches it and re-scrapes once whenever a data route returns 404
(`api.py:_data_route`).

## Search

```
GET https://hiring.cafe/_next/data/{buildId}/index.json
    ?searchState=<url-encoded JSON>
    &page=<0-based server page>
```

`searchState` keys used by this server (many more exist; the full default
object is in the site's JS):

| Key | Type | Example / values |
|---|---|---|
| `searchQuery` | string | `"python aws"` — full-text |
| `jobTitleQuery` | string | `"Data Engineer"` — title-only |
| `workplaceTypes` | string[] | `Remote`, `Hybrid`, `Onsite`, `Field` |
| `seniorityLevel` | string[] | `No Prior Experience Required`, `Entry Level`, `Mid Level`, `Senior Level` |
| `roleTypes` | string[] | `Individual Contributor`, `People Manager` |
| `departments` | string[] | LLM-assigned job categories, e.g. `Product Management`, `Information Technology`, `Software Development` (full list: `Department` literal in server.py / the site's Departments facet). Classification has gaps — high precision, not exhaustive. |
| `dateFetchedPastNDays` | int | site default 121; UI presets: 2=24h, 14=1week, 61=1month |
| `locations` | object[] | placeDetail objects from `/api/searchLocation` (below) |

The site's default searchState has many more keys (`managementYoeRange`,
`companySizeRanges`, `industries`, `excludedDepartments`, `sortBy`, …); the
full default object is in the JS chunk that defines `dateFetchedPastNDays:121`.

Response (`pageProps`):

- `ssrHits` — raw hit array. **A server page is 40 collapse groups**, but the
  raw array is larger because hits share `collapse_key`s. Server pages don't
  overlap. **Caution:** a collapse group is *coarser than a job* — observed
  (2026-06-12) grouping three different Roche roles ("Product Owner", "Head
  of Product HI Enterprise Cloud", "Team Lead Engineering") under one key,
  so deduping on `collapse_key` alone silently discards distinct jobs. The
  server dedupes on `(collapse_key, core_job_title)`: same title within a
  group = location variants of one job; different titles = different jobs.
- `ssrTotalCount` — total raw postings (pre-collapse).
- `ssrIsLastPage` — bool.
- `ssrError` — set on upstream search failure.

Page size is **not** controllable (tested `pageSize`/`size`/`limit`/
`hitsPerPage` — all ignored); the MCP server stitches its own page windows
over the fixed 40-job server pages.

### Hit fields this server reads

- `requisition_id` — stable short id; used as the MCP `job_id` and in the
  permalink `https://hiring.cafe/job/{requisition_id}`.
- `apply_url`, `is_expired`, `collapse_key`
- `job_information.title` (search hits have **no** description)
- `enriched_company_data`: `name` (preferred company name — the v5
  `company_name` is sometimes a scraped section heading), `tagline`,
  `homepage_uri`, `nb_employees`
- `v5_processed_job_data` (hiring.cafe's LLM-enriched fields):
  `core_job_title`, `formatted_workplace_location`, `workplace_type`,
  `seniority_level`, `role_type`, `commitment`,
  `estimated_publish_date`, `requirements_summary`, `technical_tools`,
  `role_activities`, `min_industry_and_role_yoe`,
  `is_compensation_transparent`, `yearly_min/max_compensation`,
  `listed_compensation_currency`, degree-requirement fields,
  `language_requirements`, `visa_sponsorship`,
  `company_sector_and_industry`, `company_tagline`, `company_website`

## Job details

```
GET https://hiring.cafe/_next/data/{buildId}/job/{requisitionId}.json
    ?requisitionId={requisitionId}
```

Response: `pageProps.job` — the same hit document as in search, **plus**
`job_information.description` (HTML, converted to plain text by the server).
Unknown ids return a page without `job`.

There is also `GET /api/job-description?id={objectID}` returning
`{job: {job_information: {description}}}` only — not used, since the data
route above gives metadata and description in one call keyed by the id we
already expose.

## Location resolution

```
GET https://hiring.cafe/api/searchLocation?query=Berlin%2C%20Germany
→ [ { "label": "...", "placeDetail": { formatted_address, types,
      address_components, geometry, ... } }, ... ]
```

The first suggestion's `placeDetail` is inserted verbatim into
`searchState.locations`. Ranking favors population, so bare city names can
resolve to US towns ("Berlin" → "New Berlin, WI") — include the country in
queries.

The place's `options` field controls scope and changes results dramatically:

- `{"radius": 50, "radius_unit": "miles", "ignore_radius": false}` — the
  website's radius filter; local jobs only (the site UI default).
- `{"flexible_regions": ["anywhere_in_continent", "anywhere_in_world"]}` —
  also include remote jobs hirable from the place's wider region; local
  results get diluted by global remote postings.

The MCP server uses the radius form when `location_radius_miles` is passed
and the flexible_regions form otherwise.

## Error signals observed

- Stale buildId → HTTP 404 on data routes.
- Heavy request volume (e.g. paginated backfills plus bulk details calls) →
  HTTP 403 "Vercel Security Checkpoint" page on **all** routes, including the
  homepage, so the buildId scrape fails too. Temporary, IP-level; observed
  2026-06-12. Raised as `BlockedError` — back off 15–60 min, do not retry in
  a loop. Pace bulk calls at 1/s.
- `POST /api/search-jobs` (an older endpoint mentioned in community
  projects) now returns 405 — do not use.
- Rate limiting → HTTP 429 (not observed in testing, handled defensively).
