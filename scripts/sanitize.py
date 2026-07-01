#!/usr/bin/env python3
"""Shared filename-label sanitization for JD and CV artifacts.

The one definition of how a company name becomes a filename label: strip
path-hostile characters, collapse whitespace. Used by ingest-jd.py (import)
and tailor-job.sh (CLI: `python3 scripts/sanitize.py "<name>"`). Stdlib only.
"""

import re
import sys


def safe_label(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r'[/\\:*?"<>|]', "", name)).strip()


if __name__ == "__main__":
    print(safe_label(" ".join(sys.argv[1:])))
