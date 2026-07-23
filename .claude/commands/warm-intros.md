---
description: Find a warm path into one job's company and draft outreach — never sends
argument-hint: <job_id | company name>
---

Find referral paths and draft outreach for one job: $ARGUMENTS

This is the one skill allowed to call the LinkedIn **person** tools
(`search_people`, `get_company_employees`, `get_person_profile`,
`get_company_profile`). The messaging tool (`send_message`) stays off-limits
inside this skill: **drafts only, never send.** Sending happens only if the
user later approves a specific draft in conversation, verbatim — and even then
it is the user's explicit call, not part of this workflow.

## 0. Resolve the job

Accept a job id or a company-name fragment, like `/promote` does:

```
sqlite3 -line data/jobs.db "SELECT job_id, company, title, status, jd_path, cv_md_path FROM jobs WHERE status IN ('shortlisted','tailored','applied') AND (job_id = '…' OR company LIKE '%…%');"
```

Zero or multiple matches: show the candidate rows and stop. One job per
invocation — never loop this skill over a list of jobs; that is exactly the
bulk usage the LinkedIn rules forbid.

**Mode** follows status: `shortlisted`/`tailored` → *pre-apply* (goal: a
referral before the application lands); `applied` → *follow-up* (goal: a
direct note to the hiring manager referencing the application).

Read the job's JD (`jd_path`) and tailored CV (`cv_md_path`) if present, plus
`data/cv.md` and `data/tailoring-notes.md` — drafts must stay inside the same
claim boundaries as CVs.

## 1. Gather (hard cap: 6 LinkedIn calls, sequential, paced)

Rules, same register as `/ingest-linkedin`:

- **≤ 6 LinkedIn tool calls total** for the whole invocation.
- One at a time, never parallel; `sleep 2` (Bash) between calls.
- On an auth error: stop and tell the user to re-run the login flow
  (`uvx mcp-server-linkedin@latest`); never retry in a loop.

Suggested spend, adapting to what each step returns:

1. `search_people` scoped to the company with a title heuristic for the
   **likely hiring manager**, derived from the JD (a "Head of Product" role →
   search "VP Product" / "CPO" at that company; a CIO role → "CEO" / "COO").
2. `search_people` scoped to the company for **1st-degree connections**
   (broad query, e.g. product/engineering/leadership keywords).
3. `get_company_employees` **only for small companies** (< ~500 employees);
   at a large company it is an unbounded scrape — prefer targeted
   `search_people` passes. Always pass a small `max_scrolls` (≤ 3).
4. `get_person_profile` on **at most 2** finalists, to confirm relevance and
   find common ground (shared employers, shared groups, home city).


Finding nothing warm is a valid outcome — a cold-but-direct hiring-manager
note is still the payoff. Do not spend extra calls hunting for a 2nd-degree
path that isn't there.

## 2. Rank paths

Rank by expected value, each with a one-line rationale:

1. 1st-degree connection **in the hiring org**
2. 1st-degree elsewhere at the company
3. Strong 2nd-degree (shared employer history, real overlap)
4. Hiring manager, cold
5. Recruiter / Talent Acquisition, cold

## 3. Draft (never send)

Produce ready-to-paste drafts for the top 1–2 paths:

- **Intro-request** to a connection: short, specific, easy to forward.
- **Direct note** to the hiring manager: pre-apply = why this role, one sharp
  relevance hook; follow-up = reference the submitted application + hook.
- Connection-request notes must fit **300 chars**; messages/InMail can be a
  short paragraph. Every claim inside CV/tailoring-note boundaries.

## 4. Persist + report

Write `data/reports/warm-intros-<job_id>-<YYYY-MM-DD>.md`: mode, candidates
table (name, profile URL, degree, role, rationale, rank), and the drafts.

Then summarize to the user: best path, why, and the next action **for the
user** (send the note themselves, or tell Claude explicitly to send a specific
draft). Do not write to `jobs.db` — outreach tracking lands with the future
outcome-tracking schema work, not here.
