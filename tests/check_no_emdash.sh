#!/usr/bin/env bash
# tests/check_no_emdash.sh - pre-publish hygiene gate: no em dash (U+2014)
# character anywhere in a tracked file.
#
# House style for this repo is plain ASCII punctuation (comma, colon,
# period, " - ", or parentheses) instead of an em dash, in prose, comments,
# and code alike. This is a generic character-presence gate, not a style
# linter - it only checks for the one codepoint. Exits 0 with a PASS line
# when nothing matches, exits 1 and prints every offending line otherwise.
#
# Same style as tests/check_no_leaks.sh: a static grep gate, no framework,
# runs in well under a second, safe to wire into a pre-push hook or CI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

echo "scanning tracked files for U+2014 (em dash) ..."

VIOLATIONS="$(git grep -nP '\x{2014}' -- . || true)"

if [[ -n "${VIOLATIONS}" ]]; then
  echo "FAIL: em dash (U+2014) found in tracked file(s):" >&2
  echo "${VIOLATIONS}" >&2
  exit 1
fi

echo "PASS: no em dash (U+2014) found in tracked files."
