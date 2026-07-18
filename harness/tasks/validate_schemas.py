#!/usr/bin/env python3
"""harness/tasks/validate_schemas.py - hand-rolled, stdlib-only schema gate.

Validates every entry of harness/tasks/task-scenarios.json against
harness/schemas/task-scenario.schema.json, and every
harness/results/tasks-run-*.json present (gitignored runtime artifacts, so
there may be zero, one, or many) against
harness/schemas/task-result-record.schema.json.

Deliberately NOT built on the third-party `jsonschema` package - this repo's
own harness/requirements.txt only pulls in Playwright/requests, and this gate
must run with nothing more than the stdlib so it can never be skipped for a
missing dependency. The checks below are explicit, hand-written Python, not a
general JSON Schema evaluator - they only implement the subset of schema
shape (required/type/enum/items/additionalProperties, plus the one
conditional the schema's own prose documents: `selector` is required on a
`field_value` success check) that this repo's two schema documents actually
use. Extend this file, not a generic validator, if the schemas grow.

Exit code 0 with a summary line on success (results-file absence is not a
failure - it is silently skipped, see main()). Exit code 1 and every
violation printed to stderr otherwise.

Usage:
    python3 harness/tasks/validate_schemas.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HARNESS_DIR = ROOT / "harness"
SCHEMAS_DIR = HARNESS_DIR / "schemas"
TASKS_DIR = HARNESS_DIR / "tasks"
RESULTS_DIR = HARNESS_DIR / "results"

SCENARIO_SCHEMA_PATH = SCHEMAS_DIR / "task-scenario.schema.json"
RECORD_SCHEMA_PATH = SCHEMAS_DIR / "task-result-record.schema.json"
SCENARIOS_PATH = TASKS_DIR / "task-scenarios.json"

RESOLVED_SOURCE_CUTOVER_NOTE = (
    "resolved_source is optional on result files predating 2026-07-17; see "
    "harness/schemas/task-result-record.schema.json's description."
)


class Violation(Exception):
    """Raised for a hard schema failure - caught at the top level of each
    validate_* function so one bad entry does not stop the scan of the rest;
    every message collected this way is a real violation, not a warning."""


def _type_ok(value, jtype):
    if jtype == "string":
        return isinstance(value, str)
    if jtype == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if jtype == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if jtype == "boolean":
        return isinstance(value, bool)
    if jtype == "object":
        return isinstance(value, dict)
    if jtype == "array":
        return isinstance(value, list)
    if jtype == "null":
        return value is None
    return False


def _check_type(value, jtype, path, violations):
    types = jtype if isinstance(jtype, list) else [jtype]
    if not any(_type_ok(value, t) for t in types):
        violations.append(f"{path}: expected type {jtype!r}, got {type(value).__name__} ({value!r})")
        return False
    return True


def _check_enum(value, enum, path, violations):
    if enum is not None and value not in enum:
        violations.append(f"{path}: value {value!r} not in enum {enum!r}")


# ---------------------------------------------------------------------------
# scenario validation (harness/schemas/task-scenario.schema.json)
# ---------------------------------------------------------------------------

def validate_scenario(entry, idx, violations):
    path = f"task-scenarios.json[{idx}] (id={entry.get('id', '<missing>')!r})"
    required = ["id", "tier", "goal", "start_page", "run_args", "success", "expect_pause", "timeout_s"]
    for field in required:
        if field not in entry:
            violations.append(f"{path}: missing required field {field!r}")

    if "id" in entry:
        _check_type(entry["id"], "string", f"{path}.id", violations)
    if "tier" in entry:
        if _check_type(entry["tier"], "string", f"{path}.tier", violations):
            _check_enum(entry["tier"], ["fixture", "realsite"], f"{path}.tier", violations)
    if "goal" in entry:
        _check_type(entry["goal"], "string", f"{path}.goal", violations)
    if "start_page" in entry:
        _check_type(entry["start_page"], "string", f"{path}.start_page", violations)
    if "run_args" in entry:
        if _check_type(entry["run_args"], "array", f"{path}.run_args", violations):
            for i, a in enumerate(entry["run_args"]):
                _check_type(a, "string", f"{path}.run_args[{i}]", violations)
    if "expect_pause" in entry:
        _check_type(entry["expect_pause"], "boolean", f"{path}.expect_pause", violations)
    if "timeout_s" in entry:
        if _check_type(entry["timeout_s"], "integer", f"{path}.timeout_s", violations):
            if entry["timeout_s"] < 1:
                violations.append(f"{path}.timeout_s: must be >= 1, got {entry['timeout_s']}")
    if "min_steps_executed" in entry:
        if _check_type(entry["min_steps_executed"], "integer", f"{path}.min_steps_executed", violations):
            if entry["min_steps_executed"] < 1:
                violations.append(f"{path}.min_steps_executed: must be >= 1, got {entry['min_steps_executed']}")

    if "success" in entry:
        if _check_type(entry["success"], "array", f"{path}.success", violations):
            if len(entry["success"]) < 1:
                violations.append(f"{path}.success: must have at least 1 entry")
            for i, check in enumerate(entry["success"]):
                validate_success_check(check, f"{path}.success[{i}]", violations)

    allowed = set(required + ["min_steps_executed"])
    for field in entry.keys():
        if field not in allowed:
            violations.append(f"{path}: unexpected field {field!r} (not in schema)")


def validate_success_check(check, path, violations):
    if not _check_type(check, "object", path, violations):
        return
    if "type" not in check:
        violations.append(f"{path}: missing required field 'type'")
    if "value" not in check:
        violations.append(f"{path}: missing required field 'value'")
    ctype = check.get("type")
    if "type" in check:
        if _check_type(ctype, "string", f"{path}.type", violations):
            _check_enum(ctype, ["url_contains", "text_visible", "field_value"], f"{path}.type", violations)
    if "value" in check:
        _check_type(check["value"], "string", f"{path}.value", violations)
    if ctype == "field_value" and "selector" not in check:
        violations.append(f"{path}: 'selector' is required when type is 'field_value'")
    if "selector" in check:
        _check_type(check["selector"], "string", f"{path}.selector", violations)
    allowed = {"type", "value", "selector"}
    for field in check.keys():
        if field not in allowed:
            violations.append(f"{path}: unexpected field {field!r} (not in schema)")


# ---------------------------------------------------------------------------
# result-file validation (harness/schemas/task-result-record.schema.json)
# ---------------------------------------------------------------------------

RESULT_ROW_ENUM_STATE = [
    "completed", "halted", "paused", "fell_to_model", "timeout",
    "harness_error", "invalid_author",
]
RESULT_ROW_ENUM_BUCKET = [
    None, "wrong_plan", "halted", "fell_to_model", "pause_unexpected",
    "timeout", "harness_error", "invalid_author",
]
RESOLVED_SOURCE_ENUM = ["harness_checks", "owner_judged", "external"]


RESULT_FILE_COUNT_FIELDS = ("n_total", "n_harness_error", "n_rated", "n_success", "buckets")


def validate_result_file(doc, fname, violations, warnings):
    path = fname
    required = ["timestamp_utc", "tier", "authored_from", "model_tag", "extension_dir", "results"]
    for field in required:
        if field not in doc:
            violations.append(f"{path}: missing required field {field!r}")

    # n_total/n_harness_error/n_rated/n_success/buckets were added to main()'s
    # output by a later fix than the wrapper's other fields (see
    # task_runner.py's "FIX 4a" comment) - a handful of this repo's own
    # gitignored local result files on disk predate that fix. Same posture as
    # resolved_source below: warn, don't fail, on a genuinely older file;
    # every file main() writes today includes all five.
    for field in RESULT_FILE_COUNT_FIELDS:
        if field not in doc:
            warnings.append(f"{path}: {field!r} absent (predates task_runner.py's FIX 4a count fields)")

    if "tier" in doc:
        if _check_type(doc["tier"], "string", f"{path}.tier", violations):
            _check_enum(doc["tier"], ["fixture", "realsite", "all"], f"{path}.tier", violations)
    for field in ("n_total", "n_harness_error", "n_rated", "n_success"):
        if field in doc:
            if _check_type(doc[field], "integer", f"{path}.{field}", violations):
                if doc[field] < 0:
                    violations.append(f"{path}.{field}: must be >= 0, got {doc[field]}")
    if "buckets" in doc:
        _check_type(doc["buckets"], "object", f"{path}.buckets", violations)

    if "results" in doc:
        if _check_type(doc["results"], "array", f"{path}.results", violations):
            for i, row in enumerate(doc["results"]):
                validate_result_row(row, f"{path}.results[{i}]", violations, warnings)

    # task-result-record.schema.json declares additionalProperties:false on
    # this top-level object.
    allowed = set(required) | set(RESULT_FILE_COUNT_FIELDS)
    for field in doc.keys():
        if field not in allowed:
            violations.append(f"{path}: unexpected field {field!r} (not in schema)")


def validate_result_row(row, path, violations, warnings):
    if not _check_type(row, "object", path, violations):
        return
    required = [
        "id", "tier", "expect_pause", "state", "success", "bucket",
        "nav_confirms", "steps_executed", "evidence", "checks", "wall_s",
    ]
    for field in required:
        if field not in row:
            violations.append(f"{path}: missing required field {field!r}")

    if "id" in row:
        _check_type(row["id"], "string", f"{path}.id", violations)
    if "tier" in row:
        if _check_type(row["tier"], "string", f"{path}.tier", violations):
            _check_enum(row["tier"], ["fixture", "realsite"], f"{path}.tier", violations)
    if "expect_pause" in row:
        _check_type(row["expect_pause"], "boolean", f"{path}.expect_pause", violations)
    if "state" in row:
        if _check_type(row["state"], "string", f"{path}.state", violations):
            _check_enum(row["state"], RESULT_ROW_ENUM_STATE, f"{path}.state", violations)
    if "success" in row:
        _check_type(row["success"], "boolean", f"{path}.success", violations)
    if "bucket" in row:
        if _check_type(row["bucket"], ["string", "null"], f"{path}.bucket", violations):
            _check_enum(row["bucket"], RESULT_ROW_ENUM_BUCKET, f"{path}.bucket", violations)
    for field in ("nav_confirms", "steps_executed"):
        if field in row:
            if _check_type(row[field], "integer", f"{path}.{field}", violations):
                if row[field] < 0:
                    violations.append(f"{path}.{field}: must be >= 0, got {row[field]}")
    if "wall_s" in row:
        if _check_type(row["wall_s"], "number", f"{path}.wall_s", violations):
            if row["wall_s"] < 0:
                violations.append(f"{path}.wall_s: must be >= 0, got {row['wall_s']}")
    if "evidence" in row:
        _check_type(row["evidence"], "object", f"{path}.evidence", violations)
    if "checks" in row:
        if _check_type(row["checks"], "array", f"{path}.checks", violations):
            for i, c in enumerate(row["checks"]):
                cpath = f"{path}.checks[{i}]"
                if not _check_type(c, "object", cpath, violations):
                    continue
                if "type" not in c:
                    violations.append(f"{cpath}: missing required field 'type'")
                if "ok" not in c:
                    violations.append(f"{cpath}: missing required field 'ok'")
                elif not _check_type(c["ok"], "boolean", f"{cpath}.ok", violations):
                    pass

    # resolved_source: optional, tolerated missing on pre-2026-07-17 files -
    # warn (not fail) when absent, validate the enum strictly when present.
    if "resolved_source" not in row:
        warnings.append(f"{path}: resolved_source absent - {RESOLVED_SOURCE_CUTOVER_NOTE}")
    else:
        if _check_type(row["resolved_source"], "string", f"{path}.resolved_source", violations):
            _check_enum(row["resolved_source"], RESOLVED_SOURCE_ENUM, f"{path}.resolved_source", violations)

    # task-result-record.schema.json declares additionalProperties:false on
    # result_row - start_url/run_verdict are the schema's other optional
    # properties beyond `required` and resolved_source (both absent on some
    # legitimate rows, e.g. invalid_author, so not enforced as required
    # here - see the schema's own per-field descriptions).
    allowed = set(required) | {"resolved_source", "start_url", "run_verdict"}
    for field in row.keys():
        if field not in allowed:
            violations.append(f"{path}: unexpected field {field!r} (not in schema)")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    violations = []
    warnings = []

    if not SCENARIOS_PATH.exists():
        print(f"FAIL: {SCENARIOS_PATH} not found", file=sys.stderr)
        return 1
    scenarios = json.loads(SCENARIOS_PATH.read_text())
    if not isinstance(scenarios, list):
        print(f"FAIL: {SCENARIOS_PATH} top level must be a JSON array", file=sys.stderr)
        return 1
    for i, entry in enumerate(scenarios):
        validate_scenario(entry, i, violations)
    print(f"checked {len(scenarios)} entries against {SCENARIO_SCHEMA_PATH.relative_to(ROOT)}")

    result_files = sorted(RESULTS_DIR.glob("tasks-run-*.json")) if RESULTS_DIR.exists() else []
    if not result_files:
        print("no harness/results/tasks-run-*.json present - skipping result-record validation")
    else:
        for fpath in result_files:
            try:
                doc = json.loads(fpath.read_text())
            except json.JSONDecodeError as e:
                violations.append(f"{fpath.name}: invalid JSON ({e})")
                continue
            validate_result_file(doc, fpath.name, violations, warnings)
        print(f"checked {len(result_files)} result file(s) against {RECORD_SCHEMA_PATH.relative_to(ROOT)}")

    for w in warnings:
        print(f"WARN: {w}")

    if violations:
        print(f"\nFAIL: {len(violations)} schema violation(s):", file=sys.stderr)
        for v in violations:
            print(f"  {v}", file=sys.stderr)
        return 1

    print("\nPASS: all checked documents match their schema.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
