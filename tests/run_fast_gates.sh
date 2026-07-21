#!/usr/bin/env bash
# tests/run_fast_gates.sh - the one command CI (and any human, pre-push)
# runs to get a fast, deterministic, zero-network, zero-model-endpoint signal
# on this repo.
#
# Runs, in order, collecting failures rather than stopping at the first one,
# then prints a summary and exits non-zero if anything failed:
#   1. tests/check_no_leaks.sh    - identity/infra string gate
#   2. tests/check_no_emdash.sh   - no U+2014 anywhere tracked
#   3. tests/check_schemas.sh     - task-scenario/result JSON matches schema
#   4. well-formedness of the static JSON files this repo ships (plain
#      json.load, stdlib-only, no jsonschema dependency, matching the style
#      of harness/tasks/validate_schemas.py)
#   5. two Node validator smokes (brainstorm/validate.js and
#      harness/tasks/resolve_go.js) against a sibling lfl-terminal checkout's
#      extension/ dir - IF that checkout is resolvable. If it is not, this is
#      a hard failure with an explanatory message, not a silent skip: CI
#      always provides the sibling checkout (see .github/workflows/ci.yml),
#      so a missing one locally means the environment is incomplete, and
#      quietly skipping the two validators that exercise the real product
#      code would weaken this gate exactly where it matters most.
#
# Deliberately out of scope (see harness/README.md): anything that drives a
# real model endpoint or a real browser (harness/runner.py, task_runner.py,
# author_tasks.py, brainstorm/probe.py's main, benchmark/load.py). Zero
# network, zero model endpoints, safe to run in CI or a pre-push hook.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

FAILED_GATES=()

run_gate() {
  local name="$1"
  shift
  echo "==> ${name}"
  if "$@"; then
    echo "--- ${name}: PASS"
  else
    echo "--- ${name}: FAIL" >&2
    FAILED_GATES+=("${name}")
  fi
  echo
}

run_gate "check_no_leaks" bash tests/check_no_leaks.sh
run_gate "check_no_emdash" bash tests/check_no_emdash.sh
run_gate "check_schemas" bash tests/check_schemas.sh

STATIC_JSON_FILES=(
  harness/tasks/task-scenarios.json
  harness/tasks/human-recipes.json
  harness/scenarios.json
  brainstorm/goals.json
)
for f in harness/schemas/*.schema.json; do
  STATIC_JSON_FILES+=("${f}")
done

json_wellformed() {
  python3 - "$@" <<'PY'
import json
import sys

bad = []
for path in sys.argv[1:]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        bad.append(f"{path}: {exc}")

if bad:
    print("FAIL: malformed JSON:", file=sys.stderr)
    for line in bad:
        print(f"  {line}", file=sys.stderr)
    sys.exit(1)

for path in sys.argv[1:]:
    print(f"ok: {path}")
sys.exit(0)
PY
}

run_gate "json_wellformed" json_wellformed "${STATIC_JSON_FILES[@]}"

# ---- Node validator smokes ----
#
# Both brainstorm/validate.js and harness/tasks/resolve_go.js shell out to
# the real lfl-terminal extension code (registry.js / nav.js) from a sibling
# checkout - see those two files' own header comments for why (zero
# reimplementation of the product's own parsing/resolution logic). Resolve
# the sibling checkout the same way those scripts do: LFL_TERMINAL_EXTENSION_DIR
# if set, else ../lfl-terminal/extension next to this repo.
EXTENSION_DIR="${LFL_TERMINAL_EXTENSION_DIR:-${ROOT}/../lfl-terminal/extension}"

if [[ ! -f "${EXTENSION_DIR}/content/registry.js" || ! -f "${EXTENSION_DIR}/content/nav.js" ]]; then
  echo "==> node_validators"
  echo "--- node_validators: FAIL" >&2
  {
    echo "FAIL: could not find a lfl-terminal extension checkout at:"
    echo "  ${EXTENSION_DIR}"
    echo "brainstorm/validate.js and harness/tasks/resolve_go.js both require"
    echo "a sibling lfl-terminal checkout's extension/ directory (its"
    echo "content/registry.js and content/nav.js) to smoke-test against."
    echo "Provide one of:"
    echo "  - a checkout at ../lfl-terminal next to this repo, or"
    echo "  - set LFL_TERMINAL_EXTENSION_DIR to point at its extension/ dir"
    echo "CI always provides this (see .github/workflows/ci.yml's second"
    echo "checkout step) - this is not silently skipped, since that would"
    echo "weaken the gate exactly where it exercises real product code."
  } >&2
  FAILED_GATES+=("node_validators")
  echo
else
  echo "==> node_validators"
  export LFL_TERMINAL_EXTENSION_DIR="${EXTENSION_DIR}"
  NODE_VALIDATORS_OK=1

  VALIDATE_JS_OUT="$(echo '{"body":"help"}' | node brainstorm/validate.js)"
  VALIDATE_JS_EXPECTED='{"ok":true,"steps":["help"],"arity":0,"usesRest":false,"stepCount":1}'
  if [[ "${VALIDATE_JS_OUT}" != "${VALIDATE_JS_EXPECTED}" ]]; then
    echo "FAIL: brainstorm/validate.js smoke mismatch:" >&2
    echo "  expected: ${VALIDATE_JS_EXPECTED}" >&2
    echo "  actual:   ${VALIDATE_JS_OUT}" >&2
    NODE_VALIDATORS_OK=0
  fi

  RESOLVE_GO_OUT="$(echo '{"arg":"example.com"}' | node harness/tasks/resolve_go.js)"
  RESOLVE_GO_EXPECTED='{"ok":true,"url":"https://example.com/","step":"literal"}'
  if [[ "${RESOLVE_GO_OUT}" != "${RESOLVE_GO_EXPECTED}" ]]; then
    echo "FAIL: harness/tasks/resolve_go.js smoke mismatch:" >&2
    echo "  expected: ${RESOLVE_GO_EXPECTED}" >&2
    echo "  actual:   ${RESOLVE_GO_OUT}" >&2
    NODE_VALIDATORS_OK=0
  fi

  if [[ "${NODE_VALIDATORS_OK}" -eq 1 ]]; then
    echo "--- node_validators: PASS"
  else
    echo "--- node_validators: FAIL" >&2
    FAILED_GATES+=("node_validators")
  fi
  echo
fi

echo "==================== summary ===================="
if [[ ${#FAILED_GATES[@]} -eq 0 ]]; then
  echo "PASS: all fast gates passed."
  exit 0
else
  echo "FAIL: ${#FAILED_GATES[@]} gate(s) failed:" >&2
  for g in "${FAILED_GATES[@]}"; do
    echo "  - ${g}" >&2
  done
  exit 1
fi
