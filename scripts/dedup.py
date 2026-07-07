"""Deterministic dedup helpers shared by the ingest arms.

Company/title normalization plus a Jaccard title-similarity match, lifted out
of the ingest-linkedin skill's prose so LinkedIn collection dedups by a fixed,
tested rule on every run instead of depending on the model re-deriving it. The
hiring.cafe arm dedups on exact `job_id` inside the MCP server; this module adds
the cross-source (LinkedIn-vs-hiring.cafe) fuzzy check that only LinkedIn needs.
"""

import re

# Legal-entity suffixes stripped from a company before comparison. Kept short
# and lowercase; matched as trailing whole tokens (see norm_company).
_COMPANY_SUFFIXES = (
    "inc", "llc", "ltd", "limited", "plc", "gmbh", "ag", "sa", "srl", "bv",
    "oy", "ab", "as", "sro", "co", "corp", "corporation", "sp z o o", "z o o",
)

# Words dropped from a title before comparison: work-mode and geography. These
# are noise for role identity. (Gender tags like f/m/x are removed separately by
# _GENDER_TAG below, before tokenization, since slashes split them into letters.)
_TITLE_STOPWORDS = {
    "remote", "hybrid", "onsite", "on", "site",
    "emea", "eea", "eu", "europe", "european", "union", "area",
}

# "(f/m/x)", "m/f/d", "w/m" and the like — a run of gender letters joined by
# slashes. Stripped before cleaning so the letters never become bare tokens.
_GENDER_TAG = re.compile(r"[fmwdnx](?:\s*/\s*[fmwdnx])+", re.IGNORECASE)

# A title Jaccard at or above this, with an identical normalized company, is
# treated as the same role. Pinned by tests in test_dedup.py — the Fabrikam
# cross-source case clears it comfortably (~0.86) while distinct C-level roles
# at one company (CPO vs CTO, ~0.5) stay separate.
CROSS_SOURCE_TITLE_THRESHOLD = 0.6


def _clean(s: str) -> str:
    """Lowercase, collapse every non-alphanumeric run to a single space."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (s or "").lower())).strip()


def norm_company(s: str) -> str:
    """Normalized company key: cleaned, with trailing legal suffixes removed."""
    c = _clean(s)
    # Strip up to two trailing suffix tokens (e.g. "foo co ltd" -> "foo").
    for _ in range(2):
        for suf in _COMPANY_SUFFIXES:
            if c != suf and c.endswith(" " + suf):
                c = c[: -len(suf) - 1].strip()
                break
        else:
            break
    return c


def norm_title(s: str) -> str:
    """Normalized title: gender tags removed, cleaned, work-mode/geo dropped."""
    s = _GENDER_TAG.sub(" ", (s or "").lower())
    return " ".join(t for t in _clean(s).split() if t not in _TITLE_STOPWORDS)


def title_sim(a: str, b: str) -> float:
    """Jaccard overlap of two normalized titles' token sets (order-insensitive)."""
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def find_cross_source_dup(company, title, existing):
    """Return the first matching (norm_company, norm_title) in `existing`, or None.

    A match is an identical normalized company AND title similarity at/above
    CROSS_SOURCE_TITLE_THRESHOLD. `existing` is an iterable of already-normalized
    (company, title) pairs — normalize the DB rows once in the caller.
    """
    nc, nt = norm_company(company), norm_title(title)
    if not nc or not nt:
        return None
    for ec, et in existing:
        if ec and ec == nc and title_sim(nt, et) >= CROSS_SOURCE_TITLE_THRESHOLD:
            return (ec, et)
    return None


def classify(records, known_ids, existing):
    """Bucket incoming LinkedIn records into (inserted, exact_dups, cross_dups).

    Pure: mutates none of its arguments; the caller performs the DB writes for
    everything in `inserted`. Records are processed in order and each accepted
    record is folded into the working known/existing sets, so a job that appears
    in more than one of the paced searches is only inserted once.

    - `records`: dicts with at least `id`, `company`, `title`.
    - `known_ids`: set of `job_id`s already in the DB.
    - `existing`: iterable of (norm_company, norm_title) pairs already in the DB.

    Returns (inserted_records, exact_ids, cross_pairs) where cross_pairs is a
    list of (linkedin_id, matched_(norm_company, norm_title)).
    """
    known = set(known_ids)
    ex = list(existing)
    inserted, exact, cross = [], [], []
    for rec in records:
        lid = f"linkedin-{rec['id']}"
        if lid in known:
            exact.append(lid)
            continue
        dup = find_cross_source_dup(rec["company"], rec["title"], ex)
        if dup:
            cross.append((lid, dup))
            continue
        inserted.append(rec)
        known.add(lid)
        ex.append((norm_company(rec["company"]), norm_title(rec["title"])))
    return inserted, exact, cross
