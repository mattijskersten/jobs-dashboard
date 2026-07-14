"""MCP server exposing hiring.cafe job search to AI agents."""

from __future__ import annotations

import html
import re
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from .api import SERVER_PAGE_SIZE, HiringCafeClient, HiringCafeError

mcp = FastMCP(
    "hiring-cafe",
    instructions=(
        "Search the hiring.cafe job aggregator. Funnel pattern: call "
        "search_jobs with filters derived from the candidate's CV, triage the "
        "compact summaries, then call get_job_details only for the few jobs "
        "worth reading in full."
    ),
)

_client = HiringCafeClient()

SeniorityLevel = Literal[
    "No Prior Experience Required", "Entry Level", "Mid Level", "Senior Level"
]
WorkplaceType = Literal["Remote", "Hybrid", "Onsite", "Field"]
RoleType = Literal["Individual Contributor", "People Manager"]
# hiring.cafe's LLM-assigned job categories (the "Departments" facet). The
# classification has gaps — treat a departments search as high-precision but
# not exhaustive, and union it with a broad `query` search for recall.
Department = Literal[
    "Administrative & Clerical Support", "Business Development",
    "Business Operations", "Communications and Public Affairs",
    "Creative and Art Services", "Custodial Services", "Customer Service",
    "Data and Analytics", "Design", "Education services", "Engineering",
    "Environment, Health, and Safety", "Finance and Accounting",
    "Food and Beverage Services", "Healthcare Services - Advanced Practice",
    "Healthcare Services - Allied Health", "Healthcare Services - Nursing",
    "Healthcare Services - Pharmacy", "Healthcare Services - Veterinary",
    "Human Resources", "Information Technology", "Legal and Compliance",
    "Marketing", "Product Management", "Project and Program Management",
    "Protective Services", "Quality Assurance",
    "Research and Development (R&D)", "Sales", "Skilled Trades - Construction",
    "Skilled Trades - General Labor", "Skilled Trades - Maintenance and Repair",
    "Skilled Trades - Manufacturing and Industrial",
    "Skilled Trades - Mechanical and Electrical", "Social Services",
    "Software Development", "Supply Chain / Logistics / Procurement",
    "Transportation Services",
]


# -- formatting helpers -------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_TAG_RE = re.compile(
    r"</?(p|div|br|li|ul|ol|h[1-6]|tr|table|section|article)[^>]*>", re.I
)


def _html_to_text(raw: str) -> str:
    """Convert a job description's HTML to readable plain text."""
    text = _BLOCK_TAG_RE.sub("\n", raw)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def _salary(v5: dict[str, Any]) -> str | None:
    if not v5.get("is_compensation_transparent"):
        return None
    lo, hi = v5.get("yearly_min_compensation"), v5.get("yearly_max_compensation")
    cur = v5.get("listed_compensation_currency") or ""
    if lo is None and hi is None:
        return None
    fmt = lambda x: f"{x:,.0f}"
    if lo is not None and hi is not None:
        rng = fmt(lo) if lo == hi else f"{fmt(lo)}–{fmt(hi)}"
    else:
        rng = fmt(lo if lo is not None else hi)
    return f"{cur} {rng}/year".strip()


def _company(hit: dict[str, Any]) -> str | None:
    enriched = hit.get("enriched_company_data") or {}
    # v5 company_name is sometimes a section heading scraped from the posting,
    # so the enriched record is more reliable.
    return enriched.get("name") or (hit.get("v5_processed_job_data") or {}).get(
        "company_name"
    )


def _summarize_hit(hit: dict[str, Any], variant_count: int = 1) -> dict[str, Any]:
    v5 = hit.get("v5_processed_job_data") or {}
    info = hit.get("job_information") or {}
    posted = v5.get("estimated_publish_date")
    yoe = v5.get("min_industry_and_role_yoe")
    summary: dict[str, Any] = {
        "id": hit.get("requisition_id"),
        "title": info.get("title") or v5.get("core_job_title"),
        "company": _company(hit),
        "location": v5.get("formatted_workplace_location"),
        "workplace_type": v5.get("workplace_type"),
        "salary": _salary(v5),
        "posted": posted[:10] if posted else None,
        "seniority": v5.get("seniority_level"),
        "role_type": v5.get("role_type"),
        "min_years_experience": yoe,
        "commitment": v5.get("commitment"),
        "requirements_summary": v5.get("requirements_summary"),
        "tech_stack": (v5.get("technical_tools") or [])[:12],
        "url": f"https://hiringcafe.com/job/{hit.get('requisition_id')}",
        "apply_url": hit.get("apply_url"),
    }
    if variant_count > 1:
        summary["other_locations"] = (
            f"posted in {variant_count} locations; this is the first variant"
        )
    return {k: v for k, v in summary.items() if v not in (None, "", [])}


def _dedupe(hits: list[dict[str, Any]]) -> list[tuple[dict[str, Any], int]]:
    """Collapse multi-location duplicates: (representative hit, variant count).

    collapse_key alone is coarser than a job — observed grouping *different*
    roles at one company under one key (see API_NOTES.md) — so it is
    subdivided by job title: same title within a collapse group = location
    variants of one job; different titles = different jobs.
    """
    groups: dict[tuple, list[dict[str, Any]]] = {}
    order: list[tuple] = []
    for h in hits:
        v5 = h.get("v5_processed_job_data") or {}
        title = (
            v5.get("core_job_title")
            or (h.get("job_information") or {}).get("title")
            or ""
        )
        key = (h.get("collapse_key") or h.get("id") or id(h), title.strip().lower())
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(h)
    return [(groups[k][0], len(groups[k])) for k in order]


# -- tools --------------------------------------------------------------------


@mcp.tool
def search_jobs(
    query: Annotated[
        str,
        Field(
            description=(
                "Free-text keywords matched against the whole posting — "
                "skills, technologies, role keywords (e.g. 'senior python "
                "aws'). Use this for the CV's core skills."
            )
        ),
    ] = "",
    job_title: Annotated[
        str,
        Field(
            description=(
                "Match against the job title only (e.g. 'Data Engineer'). "
                "Narrower than `query`; combine both for precision."
            )
        ),
    ] = "",
    location: Annotated[
        str,
        Field(
            description=(
                "City, region or country. Include the country to disambiguate "
                "(e.g. 'Berlin, Germany' not 'Berlin'). The response echoes "
                "the resolved place in `filters_applied.location` — check it. "
                "Remote jobs available from that place are included."
            )
        ),
    ] = "",
    workplace_types: Annotated[
        list[WorkplaceType] | None,
        Field(
            description=(
                "Restrict to these arrangements, e.g. ['Remote'] for "
                "remote-only. Omit for all."
            )
        ),
    ] = None,
    seniority_levels: Annotated[
        list[SeniorityLevel] | None,
        Field(description="Restrict to these seniority levels. Omit for all."),
    ] = None,
    role_types: Annotated[
        list[RoleType] | None,
        Field(
            description=(
                "Restrict by management responsibility: ['People Manager'] "
                "for roles with direct reports, ['Individual Contributor'] "
                "for IC roles. Omit for both. A strong noise filter when "
                "searching leadership roles with a broad `query`."
            )
        ),
    ] = None,
    departments: Annotated[
        list[Department] | None,
        Field(
            description=(
                "Restrict to hiring.cafe's job categories (e.g. 'Product "
                "Management', 'Information Technology'). High precision but "
                "the classification has gaps — for full recall, union the "
                "results with a broad `query` search rather than relying on "
                "departments alone."
            )
        ),
    ] = None,
    location_radius_miles: Annotated[
        int | None,
        Field(
            ge=1,
            le=500,
            description=(
                "With `location`: only jobs within this radius of the place, "
                "like the website's radius filter. Omit for the default "
                "behavior, which also includes remote jobs hirable from the "
                "location's continent/world — far more results, but local "
                "ones are diluted by global remote postings. Use a radius "
                "(e.g. 50) for the on-site/hybrid pass and a separate "
                "workplace_types=['Remote'] search without `location` for "
                "the remote pass."
            ),
        ),
    ] = None,
    posted_within_days: Annotated[
        int | None,
        Field(
            ge=1,
            le=365,
            description=(
                "Only jobs first seen within the past N days (e.g. 14). "
                "Default: site default of ~4 months."
            ),
        ),
    ] = None,
    page: Annotated[
        int, Field(ge=1, description="1-based page number for pagination.")
    ] = 1,
    page_size: Annotated[
        int,
        Field(
            ge=1,
            le=50,
            description=(
                "Results per page (default 20, max 50). Keep small; fetch the "
                "next page only if nothing on this one qualifies."
            ),
        ),
    ] = 20,
) -> dict[str, Any]:
    """Search hiring.cafe job postings with structured filters.

    Call this first, with filters derived from the candidate's CV. Returns
    compact summaries — title, company, location, salary, posting date,
    seniority, tech stack and a requirements summary — that carry enough
    signal to decide which jobs deserve a get_job_details call. Duplicate
    postings of the same job in multiple locations are collapsed to one
    result. All filters are ANDed; at least one of query/job_title/location
    should be set or results will be an unfocused firehose.
    """
    search_state: dict[str, Any] = {}
    if query.strip():
        search_state["searchQuery"] = query.strip()
    if job_title.strip():
        search_state["jobTitleQuery"] = job_title.strip()
    if workplace_types:
        search_state["workplaceTypes"] = sorted(set(workplace_types))
    if seniority_levels:
        search_state["seniorityLevel"] = sorted(set(seniority_levels))
    if role_types:
        search_state["roleTypes"] = sorted(set(role_types))
    if departments:
        search_state["departments"] = sorted(set(departments))
    if posted_within_days is not None:
        search_state["dateFetchedPastNDays"] = posted_within_days

    resolved_location = None
    try:
        if location_radius_miles is not None and not location.strip():
            raise ToolError(
                "location_radius_miles requires a `location` to anchor the "
                "radius."
            )
        if location.strip():
            place = _client.resolve_location(
                location.strip(), radius_miles=location_radius_miles
            )
            if place is None:
                raise ToolError(
                    f"hiring.cafe does not recognize the location "
                    f"'{location}'. Try a larger nearby city or just the "
                    "country name."
                )
            resolved_location = place.get("formatted_address")
            search_state["locations"] = [place]

        # The upstream API serves fixed pages of 40 unique jobs; stitch them
        # into the caller's page/page_size window.
        offset = (page - 1) * page_size
        first_server_page = offset // SERVER_PAGE_SIZE
        last_server_page = (offset + page_size - 1) // SERVER_PAGE_SIZE

        jobs: list[dict[str, Any]] = []
        total_jobs: int | None = None
        upstream_exhausted = False
        for sp in range(first_server_page, last_server_page + 1):
            props = _client.search(search_state, sp)
            total_jobs = props.get("ssrTotalCount")
            jobs.extend(
                _summarize_hit(h, n) for h, n in _dedupe(props["ssrHits"] or [])
            )
            if props.get("ssrIsLastPage") or not props["ssrHits"]:
                upstream_exhausted = True
                break
    except HiringCafeError as exc:
        raise ToolError(str(exc)) from exc

    window = jobs[offset - first_server_page * SERVER_PAGE_SIZE :][:page_size]
    has_more = not upstream_exhausted or len(
        jobs
    ) > offset - first_server_page * SERVER_PAGE_SIZE + len(window)

    result: dict[str, Any] = {
        "jobs": window,
        "page": page,
        "page_size": page_size,
        "total_postings": total_jobs,
        "has_more": has_more,
        "filters_applied": {
            k: v
            for k, v in {
                "query": query.strip() or None,
                "job_title": job_title.strip() or None,
                "location": resolved_location,
                "location_radius_miles": location_radius_miles,
                "workplace_types": workplace_types,
                "seniority_levels": seniority_levels,
                "role_types": role_types,
                "departments": departments,
                "posted_within_days": posted_within_days,
            }.items()
            if v
        },
    }
    if not window:
        result["hint"] = (
            "No results on this page. Broaden the search: fewer keywords, "
            "drop the job_title filter, widen the location, or increase "
            "posted_within_days."
        )
    if total_jobs:
        result["note"] = (
            "total_postings counts raw postings before multi-location "
            "duplicates are collapsed; the number of unique jobs is lower."
        )
    return result


@mcp.tool
def get_job_details(
    job_id: Annotated[
        str,
        Field(description="The `id` of a job returned by search_jobs."),
    ],
) -> dict[str, Any]:
    """Fetch the full description and metadata for one job.

    Call this only for jobs whose search_jobs summary already looks like a
    match — the description is long and costs context. Returns the complete
    posting text (plain text), application URL, salary, requirements,
    education/experience demands, benefits and company information.
    """
    try:
        hit = _client.get_job(job_id)
    except HiringCafeError as exc:
        raise ToolError(str(exc)) from exc

    v5 = hit.get("v5_processed_job_data") or {}
    info = hit.get("job_information") or {}
    enriched = hit.get("enriched_company_data") or {}
    posted = v5.get("estimated_publish_date")

    details: dict[str, Any] = {
        "id": hit.get("requisition_id"),
        "title": info.get("title") or v5.get("core_job_title"),
        "company": _company(hit),
        "location": v5.get("formatted_workplace_location"),
        "workplace_type": v5.get("workplace_type"),
        "salary": _salary(v5),
        "posted": posted[:10] if posted else None,
        "seniority": v5.get("seniority_level"),
        "role_type": v5.get("role_type"),
        "commitment": v5.get("commitment"),
        "min_years_experience": v5.get("min_industry_and_role_yoe"),
        "education": {
            "bachelors": v5.get("bachelors_degree_requirement"),
            "bachelors_fields": v5.get("bachelors_degree_fields_of_study"),
            "masters": v5.get("masters_degree_requirement"),
        },
        "language_requirements": v5.get("language_requirements"),
        "visa_sponsorship": v5.get("visa_sponsorship"),
        "requirements_summary": v5.get("requirements_summary"),
        "tech_stack": v5.get("technical_tools"),
        "role_activities": v5.get("role_activities"),
        "is_expired": hit.get("is_expired") or None,
        "company_info": {
            "tagline": enriched.get("tagline") or v5.get("company_tagline"),
            "website": enriched.get("homepage_uri") or v5.get("company_website"),
            "industry": v5.get("company_sector_and_industry"),
            "employees": enriched.get("nb_employees"),
        },
        "url": f"https://hiringcafe.com/job/{hit.get('requisition_id')}",
        "apply_url": hit.get("apply_url"),
        "description": _html_to_text(info.get("description") or "")
        or "(no description available)",
    }
    details["education"] = {
        k: v
        for k, v in details["education"].items()
        if v not in (None, "", [], "Not Mentioned")
    } or None
    details["company_info"] = {
        k: v for k, v in details["company_info"].items() if v not in (None, "", [])
    } or None
    return {k: v for k, v in details.items() if v not in (None, "", [])}


def main() -> None:
    mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
