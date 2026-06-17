#!/usr/bin/env python3
"""One-off: overlap between LinkedIn job search results and jobs.db.

Usage: python3 scripts/compare-linkedin.py <linkedin-results.json>

The JSON file is produced by a LinkedIn MCP session:
{"searches": [...], "jobs": [{"title", "company", "location", "posted", "url"}]}

Matching is company-first (normalized name), then title similarity within
the company's jobs, since the two sites format titles differently.
"""

import json
import re
import sqlite3
import sys
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_SUFFIXES = re.compile(
    r"\b(inc|llc|ltd|gmbh|sp z o o|s a|sa|plc|corp|corporation|company|"
    r"co|group|holdings)\b\.?",
    re.I,
)


def norm_company(name: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    s = _SUFFIXES.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_title(title: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", (title or "").lower())
    s = re.sub(r"\b(m/f/d|f/m/d|remote|hybrid|emea)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def title_sim(a: str, b: str) -> float:
    return SequenceMatcher(None, norm_title(a), norm_title(b)).ratio()


def main() -> None:
    data = json.loads(Path(sys.argv[1]).read_text())
    li_jobs = data["jobs"]

    db = sqlite3.connect(ROOT / "data" / "jobs.db")
    db_jobs = db.execute(
        "SELECT job_id, company, title, status, score FROM jobs"
    ).fetchall()
    by_company: dict[str, list] = {}
    for row in db_jobs:
        by_company.setdefault(norm_company(row[1]), []).append(row)

    def company_candidates(name: str) -> list:
        """Exact normalized match, else substring match either way
        ("johnson johnson innovative medicine" ↔ "johnson johnson")."""
        key = norm_company(name)
        if key in by_company:
            return by_company[key]
        return [
            row
            for k, rows in by_company.items()
            if k and key and (k in key or key in k)
            for row in rows
        ]

    matches, li_only = [], []
    for lj in li_jobs:
        cands = company_candidates(lj.get("company", ""))
        best = max(
            ((title_sim(lj.get("title", ""), c[2]), c) for c in cands),
            default=(0.0, None),
        )
        if best[0] >= 0.55:
            matches.append((lj, best[1], best[0]))
        else:
            li_only.append(lj)

    print(f"LinkedIn jobs (deduped): {len(li_jobs)}")
    print(f"Also found by our pipeline: {len(matches)}")
    print(f"LinkedIn-only (pipeline never saw): {len(li_only)}\n")

    if matches:
        print("== Overlap (LinkedIn ↔ jobs.db) ==")
        for lj, row, sim in sorted(matches, key=lambda m: -m[2]):
            print(
                f"  {lj.get('company')}: {lj.get('title')!r} ≈ {row[2]!r}"
                f"  [db: {row[3]}, score {row[4]}, sim {sim:.2f}]"
            )
    if li_only:
        print("\n== LinkedIn-only ==")
        for lj in li_only:
            print(
                f"  {lj.get('company')} — {lj.get('title')}"
                f" ({lj.get('location', '?')}, posted {lj.get('posted', '?')})"
            )


if __name__ == "__main__":
    main()
