# hiring-cafe-mcp

An MCP server that lets AI agents search [hiring.cafe](https://hiring.cafe/)
for jobs. Built for the CV-matching funnel: structured filters narrow the
field, compact search summaries drive triage, and full descriptions are
fetched only for finalists.

It talks to hiring.cafe's **unofficial** internal API (no authentication, no
browser). The endpoints are documented in [API_NOTES.md](API_NOTES.md) — read
that first when something breaks, because the API can change without notice.

## Setup

Requires Python ≥ 3.10 and [uv](https://docs.astral.sh/uv/).

```sh
cd hiring-cafe-mcp
uv sync
```

## Running

The server speaks MCP over stdio:

```sh
uv run hiring-cafe-mcp
```

### Register in Claude Code

```sh
claude mcp add hiring-cafe -- uv --directory /absolute/path/to/hiring-cafe-mcp run hiring-cafe-mcp
```

### Generic MCP client config (e.g. Claude Desktop)

```json
{
  "mcpServers": {
    "hiring-cafe": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/hiring-cafe-mcp", "run", "hiring-cafe-mcp"]
    }
  }
}
```

## Tools

### `search_jobs`

Structured search returning compact, triage-ready summaries. Duplicate
postings of one job in many locations are collapsed to a single result.

| Parameter | Type | Notes |
|---|---|---|
| `query` | string | Free-text keywords over the whole posting (skills, tech) |
| `job_title` | string | Matched against the title only |
| `location` | string | Free text; include the country ("Berlin, Germany") |
| `location_radius_miles` | int | With `location`: local jobs within the radius only (like the website's radius filter). Without it, remote jobs hirable from the location's continent/world are included too — local results get diluted. |
| `workplace_types` | list | Any of `Remote`, `Hybrid`, `Onsite`, `Field` |
| `seniority_levels` | list | `No Prior Experience Required`, `Entry Level`, `Mid Level`, `Senior Level` |
| `role_types` | list | `People Manager`, `Individual Contributor` — strong noise filter for leadership searches |
| `departments` | list | hiring.cafe job categories, e.g. `Product Management`, `Information Technology`. High precision but the classification has gaps — union with a broad `query` for recall. |
| `posted_within_days` | int | 1–365 |
| `page` | int | 1-based |
| `page_size` | int | default 20, max 50 |

Example call:

```json
{
  "query": "python aws",
  "workplace_types": ["Remote"],
  "seniority_levels": ["Senior Level"],
  "posted_within_days": 14,
  "page_size": 10
}
```

Each result carries `id`, `title`, `company`, `location`, `workplace_type`,
`salary` (when listed), `posted`, `seniority`, `role_type` (People Manager /
Individual Contributor), `requirements_summary`, `tech_stack`, a hiring.cafe
`url`, and the `apply_url` on the company's own hiring portal.

### `get_job_details`

Full posting for one job, by the `id` from `search_jobs`:

```json
{ "job_id": "lt0fzbk5ziniavug" }
```

Returns the complete description as plain text plus structured metadata:
apply URL, salary, education/experience requirements, language requirements,
visa sponsorship, benefits-adjacent flags and company info.

## Error behavior

Failures surface as MCP tool errors with actionable messages, not crashes:
rate limits (HTTP 429) are retried up to 3 times with exponential backoff
(1s/2s/4s, honoring `Retry-After`) before erroring, unrecognized locations suggest
broadening, removed jobs are reported as gone, and upstream shape changes
point at API_NOTES.md. The Next.js build id that the data routes require is
re-resolved automatically when the site deploys.
