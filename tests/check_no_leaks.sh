#!/usr/bin/env bash
# tests/check_no_leaks.sh - pre-publish hygiene gate for this public repo.
#
# Greps every TRACKED file for a small set of identity/infra strings that must
# never end up in a public commit (dev-machine hostnames, local absolute paths,
# tailnet addresses, an upstream model host, internal codenames, personal
# contact info). This is dev infra for a security-conscious project, so the
# very first commit must pass this gate, and it is safe to wire into a pre-push
# hook or CI. Exits 0 with a PASS line when nothing matches, exits 1 and prints
# every offending line otherwise.
#
# IMPORTANT - this script is itself a tracked file and necessarily contains the
# leak patterns as literal text (that is how it greps for them). It excludes
# ITSELF by path from the scan so it can never trip its own check; every other
# tracked file is fair game, patterns included, with no other exclusions.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SELF_PATH="tests/check_no_leaks.sh"

cd "${ROOT}"

# Extendable pattern list - add new identity/infra strings here as they turn
# up. Kept as plain array entries (not a single pre-joined regex literal) so it
# is easy to scan, diff, and extend one line at a time. The connection to any
# real upstream model, its host, and its key lives ONLY in a gitignored
# .env.local (see proxy/.env.example) - never in a tracked file, which is what
# this gate exists to guarantee.
LEAK_PATTERNS=(
  # dev-machine paths and user names
  'butter-ubuntu'
  'butter-lab'
  'butter-nas'
  'QweClau'
  '/home/'
  'OWCsecure'
  'main-ubuntu'
  'hybrid/workspace'
  'supervised-ops-demo'
  # personal contact
  'meltedrubberducky'
  '@proton'
  # tailnet / LAN / fleet addresses and codenames
  '100.71.181.10'
  '10.0.0.'
  '.ts.net'
  'llama-hermes'
  'hermes'
)

# Build one alternation regex for a single grep pass over the whole tree.
REGEX="$(IFS='|'; echo "${LEAK_PATTERNS[*]}")"

echo "scanning tracked files for pre-publish identity/infra leaks ..."

VIOLATIONS="$(git grep -nIE "${REGEX}" -- . ":!${SELF_PATH}" || true)"

if [[ -n "${VIOLATIONS}" ]]; then
  echo "FAIL: possible identity/infra leak(s) found in tracked files:" >&2
  echo "${VIOLATIONS}" >&2
  exit 1
fi

echo "PASS: no identity/infra leak patterns found in tracked files."
