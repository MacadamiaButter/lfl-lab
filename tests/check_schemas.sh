#!/usr/bin/env bash
# tests/check_schemas.sh - pre-publish gate: task-success bench shapes match
# their formal schemas.
#
# Thin wrapper around harness/tasks/validate_schemas.py (hand-rolled,
# stdlib-only - no jsonschema dependency), in the same style as
# tests/check_no_leaks.sh / tests/check_no_emdash.sh: exits 0 with a PASS
# line on success, exits 1 with the validator's own violation output
# otherwise. Safe to wire into a pre-push hook or CI - runs in well under a
# second, and result-file validation is skipped silently when
# harness/results/ (gitignored runtime artifacts) has nothing in it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

echo "validating harness/tasks/task-scenarios.json and any harness/results/tasks-run-*.json against harness/schemas/ ..."

python3 harness/tasks/validate_schemas.py
