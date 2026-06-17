#!/usr/bin/env bash
# Usage:
#   ./build.sh                              → data/cv.md → data/cv-output.pdf
#   ./build.sh "cv Foo.md"                 → that file → cv Foo.pdf
#   ./build.sh input.md output.pdf          → explicit input and output
# Template and filter are resolved relative to this script, so it can be
# invoked from anywhere in the repo (e.g. on files under data/cvs/).
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"
MASTER="$ROOT/data/cv.md"

IN="${1:-$MASTER}"
OUT="${2:-${IN%.md}.pdf}"
[ "$IN" = "$MASTER" ] && OUT="${2:-$ROOT/data/cv-output.pdf}"

pandoc "$IN" \
  --template="$DIR/cv-template.tex" \
  --lua-filter="$DIR/cv-filter.lua" \
  --pdf-engine=xelatex \
  -o "$OUT"
echo "Built: $OUT"
