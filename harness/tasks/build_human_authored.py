#!/usr/bin/env python3
"""harness/tasks/build_human_authored.py - L1 "handwritten ceiling row" adapter.

Design doc: LFL-TERMINAL-RECIPES-THAT-SUCCEED-DESIGN.md section 6, item L1
(2026-07-17, kept outside this repo alongside the operator's other planning
docs).

harness/task_runner.py (Phase B) already accepts ANY JSON shaped like Phase
A's authored-<model>-<condition>-<ts>.json output - {"model_tag": ...,
"goals": {"<id>": {"first_valid_body": "<script body>"}, ...}} - via its
--authored flag (see that file's main(), which does
`authored.get("goals", authored)`). This script is the THIN adapter the task
brief asks for: it reads the committed, hand-authored, rationale-commented
harness/tasks/human-recipes.json, substitutes the real corpus port into each
body's literal `go {PORT}/...` first step (imported from harness/runner.py's
own PORT_A - never hardcoded here, so this stays correct if
LFL_LAB_CORPUS_PORT_A is overridden), validates every body against the REAL
parseScriptBody() (via brainstorm/probe.py's validate_body(), the exact same
validator author_tasks.py's model-authored scripts go through and
task_runner.py's own run_one_scenario() calls again before seeding), and
writes an authored-shaped JSON to harness/results/ (gitignored) that
task_runner.py can consume completely unmodified.

It does NOT reimplement, fork, or duplicate any of task_runner.py's seeding/
driving/scoring logic - it only produces the one input file shape that
script already knows how to read.

Usage:
    python3 harness/tasks/build_human_authored.py
    python3 harness/task_runner.py --tier fixture --authored harness/results/authored-human-<ts>.json

Exits nonzero (before writing anything) if any recipe body fails the real
parseScriptBody() validation - a hand-authored recipe that cannot even parse
is a bug in this file, not something to silently skip.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
HARNESS_DIR = ROOT / "harness"
TASKS_DIR = HARNESS_DIR / "tasks"
RECIPES_PATH = TASKS_DIR / "human-recipes.json"
RESULTS_DIR = HARNESS_DIR / "results"  # gitignored - see .gitignore

sys.path.insert(0, str(HARNESS_DIR))
from runner import PORT_A  # noqa: E402  (path insert must happen first)

sys.path.insert(0, str(ROOT / "brainstorm"))
from probe import validate_body  # noqa: E402


def main():
    recipes = json.loads(RECIPES_PATH.read_text())
    goals_in = recipes.get("goals", {})
    if not goals_in:
        print("no goals found in human-recipes.json", file=sys.stderr)
        return 1

    base_url = f"http://127.0.0.1:{PORT_A}"
    goals_out = {}
    n_invalid = 0

    for goal_id, entry in sorted(goals_in.items()):
        raw_body = entry["body"]
        body = raw_body.replace("{PORT}", base_url)
        verdict = validate_body(body)
        if not verdict.get("ok"):
            n_invalid += 1
            print(f"INVALID  {goal_id}: {verdict.get('reason')}", file=sys.stderr)
            goals_out[goal_id] = {
                "attempts": [{"raw_body": body, "valid": False, "reason": verdict.get("reason"), "step_count": None}],
                "first_valid_body": None,
            }
            continue
        print(f"valid    {goal_id}  ({verdict.get('stepCount')} steps)")
        goals_out[goal_id] = {
            "attempts": [{"raw_body": body, "valid": True, "reason": None, "step_count": verdict.get("stepCount")}],
            "first_valid_body": body,
        }

    if n_invalid:
        print(
            f"\n{n_invalid} recipe(s) failed real parseScriptBody() validation - "
            "fix harness/tasks/human-recipes.json before running task_runner.py "
            "(a hand-authored recipe that cannot parse is this file's bug, not "
            "an engine bug - not writing an output file).",
            file=sys.stderr,
        )
        return 1

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = {
        "timestamp_utc": timestamp,
        "condition": "human",
        "tier": "fixture",
        "endpoint": None,
        "model_tag": "human",
        "attempts_per_goal": 1,
        "n_goals": len(goals_out),
        "n_valid_attempt1": len(goals_out) - n_invalid,
        "n_valid_any_attempt": len(goals_out) - n_invalid,
        "goals": goals_out,
    }
    out_path = RESULTS_DIR / f"authored-human-{timestamp}.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nwrote {out_path}")
    print(f"next: python3 harness/task_runner.py --tier fixture --authored {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
