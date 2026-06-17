#!/usr/bin/env bash
# Usage:
#   ./build.sh                              → cv.md → cv-output.pdf
#   ./build.sh "cv Foo.md"                 → that file → cv Foo.pdf
#   ./build.sh input.md output.pdf          → explicit input and output
# Template and filter are resolved relative to this script, so it can be
# invoked from anywhere in the repo (e.g. on files under data/cvs/).
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

IN="${1:-$DIR/cv.md}"
OUT="${2:-${IN%.md}.pdf}"
[ "$IN" = "$DIR/cv.md" ] && OUT="${2:-$DIR/cv-output.pdf}"

pandoc "$IN" \
  --template="$DIR/cv-template.tex" \
  --lua-filter="$DIR/cv-filter.lua" \
  --pdf-engine=xelatex \
  -o "$OUT"
echo "Built: $OUT"
