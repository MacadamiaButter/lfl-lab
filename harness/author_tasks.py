#!/usr/bin/env python3
"""harness/author_tasks.py - TASK-SUCCESS BENCH, Phase A (AUTHOR).

Design doc: LFL-LAB-TASK-SUCCESS-BENCH-DESIGN.md (2026-07-17, approved,
kept outside this repo alongside the operator's other planning docs) - see
section 3 "Design: decomposed two-phase pipeline" and section 8 "Build
plan" item 2.

For each goal in harness/tasks/task-scenarios.json (filtered by --tier), this
makes 2 authoring attempts against LFL_BRAINSTORM_ENDPOINT using the REAL
shipped wire payload - build_shipped_payload()/extract_shipped_script() are
imported unmodified from brainstorm/probe.py, which itself shells out to
shipped_payload.js (loads the real, unmodified service-worker.js and calls
its real buildBrainstormPayload()) and validate.js (loads the real,
unmodified registry.js and calls its real parseScriptBody()). Nothing about
"what makes a script valid" or "what the product actually sends the model"
is reimplemented here - see those two files' own headers for why that
matters (zero-reimplementation, zero drift).

This is a read-only inference client, no browser, no extension load. Phase B
(harness/task_runner.py) is what actually executes an authored script
against the real extension.

Usage:
    export LFL_BRAINSTORM_ENDPOINT=http://127.0.0.1:1241   # 4B, keyless, local
    python3 harness/author_tasks.py --tier fixture

    export LFL_BRAINSTORM_ENDPOINT=http://<fleet-host>:1236
    export LFL_BRAINSTORM_API_KEY="$(cat /path/to/key)"    # 35B run, later, not by this build
    python3 harness/author_tasks.py --tier fixture

Output: harness/results/authored-<modeltag>-<utcts>.json (gitignored, not
committed - see harness/README.md and .gitignore), keyed by goal id:
    { "<goal id>": {
        "attempts": [ {"raw_body": ..., "valid": bool, "reason": ..., "step_count": ...}, ... ],
        "first_valid_body": <string or null>
      }, ... }

Never prints, logs, or writes LFL_BRAINSTORM_API_KEY - same posture as
brainstorm/probe.py (see that file's header).
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HARNESS_DIR = ROOT / "harness"
TASKS_DIR = HARNESS_DIR / "tasks"
SCENARIOS_PATH = TASKS_DIR / "task-scenarios.json"
RESULTS_DIR = HARNESS_DIR / "results"  # gitignored - see .gitignore

sys.path.insert(0, str(ROOT / "brainstorm"))
from probe import (  # noqa: E402  (path insert must happen first)
    build_shipped_payload,
    extract_shipped_script,
    post_payload,
    strip_code_fence,
    validate_body,
)

ATTEMPTS_PER_GOAL = 2  # design doc section 6: 2 authoring attempts, temperature 0.2
INTER_ATTEMPT_DELAY_S = 1.0  # same polite-sequential-client posture as probe.py

# Second measured condition (owner-approved 2026-07-17, follow-up to the
# go-preamble finding): identical goals, prefixed with an explicit statement
# that no navigation is needed. The shipped payload carries no page context,
# so this preamble is the ONLY way a goal can tell the model it is already
# where it needs to be. Reported alongside the baseline condition, never
# replacing it - it separates "model always invents a destination" from
# "model follows the goal's stated context".
ON_SITE_PREAMBLE = "You are already on the correct site. "


def read_scenarios(tier):
    scenarios = json.loads(SCENARIOS_PATH.read_text())
    if tier != "all":
        scenarios = [s for s in scenarios if s.get("tier") == tier]
    return scenarios


def get_model_tag(endpoint):
    """Best-effort health check + model-identity tag, same technique and
    same reasoning as harness/runner.py's check_model_endpoint(): always a
    loopback or private-network address, never something that should go
    over Tor or a corporate proxy, so the ambient HTTP(S)_PROXY is bypassed
    unconditionally. Never fatal - an unreachable endpoint just means every
    goal's attempts will fail individually with a clear "model request
    failed" reason, which is more useful than refusing to run at all."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"{endpoint.rstrip('/')}/v1/models", timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
            models = data.get("data") or data.get("models") or []
            if models:
                ident = models[0].get("id") or models[0].get("name") or "model"
                return Path(ident).name if "/" in ident else ident
    except Exception as exc:  # noqa: BLE001
        return f"unreachable ({exc.__class__.__name__})"
    return "unknown"


def author_one_goal(endpoint, api_key, goal_text):
    attempts = []
    for attempt_n in range(1, ATTEMPTS_PER_GOAL + 1):
        try:
            payload = build_shipped_payload(goal_text)
            raw_content = post_payload(endpoint, api_key, payload)
        except Exception as err:  # noqa: BLE001 - one bad attempt must not kill the run
            attempts.append({
                "raw_body": None,
                "valid": False,
                "reason": f"model request failed: {err.__class__.__name__}: {err}",
                "step_count": None,
            })
            if attempt_n < ATTEMPTS_PER_GOAL:
                time.sleep(INTER_ATTEMPT_DELAY_S)
            continue

        script, err_reason = extract_shipped_script(raw_content)
        if script is None:
            attempts.append({
                "raw_body": raw_content,
                "valid": False,
                "reason": err_reason,
                "step_count": None,
            })
            if attempt_n < ATTEMPTS_PER_GOAL:
                time.sleep(INTER_ATTEMPT_DELAY_S)
            continue

        body = strip_code_fence(script)
        verdict = validate_body(body)
        attempts.append({
            "raw_body": body,
            "valid": bool(verdict.get("ok")),
            "reason": None if verdict.get("ok") else verdict.get("reason"),
            "step_count": verdict.get("stepCount"),
        })
        if attempt_n < ATTEMPTS_PER_GOAL:
            time.sleep(INTER_ATTEMPT_DELAY_S)
    return attempts


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--tier", choices=["fixture", "realsite", "all"], default="fixture",
        help="which task-scenarios.json tier to author scripts for (default: fixture)",
    )
    parser.add_argument("--only", action="append", default=None, help="goal id to author (repeatable); default: all in --tier")
    parser.add_argument(
        "--condition", choices=["baseline", "on-site"], default="baseline",
        help="goal-phrasing condition: baseline = goals verbatim; on-site = each goal "
             "prefixed with an explicit already-on-the-site statement (default: baseline)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    endpoint = os.environ.get("LFL_BRAINSTORM_ENDPOINT")
    if not endpoint:
        print(
            "LFL_BRAINSTORM_ENDPOINT is not set - point it at your model host, "
            "e.g. export LFL_BRAINSTORM_ENDPOINT=http://127.0.0.1:1241",
            file=sys.stderr,
        )
        sys.exit(1)
    api_key = os.environ.get("LFL_BRAINSTORM_API_KEY", "")

    # Fail fast, before spending any model calls, if the product checkout is
    # missing or has renamed something shipped_payload.js depends on - same
    # preflight posture as probe.py's own main().
    try:
        build_shipped_payload("author_tasks preflight - not sent to any model")
    except Exception as err:  # noqa: BLE001
        print(f"preflight failed: {err}", file=sys.stderr)
        sys.exit(1)

    scenarios = read_scenarios(args.tier)
    if args.only:
        wanted = set(args.only)
        scenarios = [s for s in scenarios if s["id"] in wanted]
        missing = wanted - {s["id"] for s in scenarios}
        if missing:
            sys.stderr.write(f"WARNING: unknown goal id(s) requested: {sorted(missing)}\n")

    model_tag = get_model_tag(endpoint)
    print(f"[setup] LFL_BRAINSTORM_ENDPOINT={endpoint} -> model tag: {model_tag}", file=sys.stderr)
    print(f"authoring {len(scenarios)} goal(s) (--tier {args.tier}, shipped payload, {ATTEMPTS_PER_GOAL} attempts each)...", file=sys.stderr)

    results = {}
    for i, scenario in enumerate(scenarios, start=1):
        goal_id = scenario["id"]
        goal_text = scenario["goal"]
        if args.condition == "on-site":
            goal_text = ON_SITE_PREAMBLE + goal_text
        print(f"[{i}/{len(scenarios)}] {goal_id} ...", file=sys.stderr)
        attempts = author_one_goal(endpoint, api_key, goal_text)
        first_valid = next((a["raw_body"] for a in attempts if a["valid"]), None)
        results[goal_id] = {"attempts": attempts, "first_valid_body": first_valid}

    n = len(results)
    # FIX 4b (verify-pass correction): design doc section 6's authored_valid
    # metric is explicitly "a goal counts valid if attempt 1 is valid -
    # attempt 2 is recorded for stability info only, keeping the headline
    # comparable to the shipped probe method" - the pre-fix code only ever
    # computed the "any of the 2 attempts" number and called it n_valid,
    # which is a DIFFERENT (and always-greater-or-equal) quantity than the
    # design's own headline. Report both, named unambiguously.
    n_valid_attempt1 = sum(1 for r in results.values() if r["attempts"] and r["attempts"][0]["valid"])
    n_valid_any_attempt = sum(1 for r in results.values() if r["first_valid_body"] is not None)
    print(
        f"\n{n_valid_attempt1}/{n} goals produced a validator-passing script on attempt 1 "
        f"(headline, design doc section 6); {n_valid_any_attempt}/{n} on attempt 1 or 2 (any-attempt, stability info only).",
        file=sys.stderr,
    )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_tag = "".join(c if (c.isalnum() or c in "-_.") else "-" for c in model_tag)
    out_path = RESULTS_DIR / f"authored-{safe_tag}-{args.condition}-{ts}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp_utc": ts,
                "condition": args.condition,
                "tier": args.tier,
                "endpoint": endpoint,
                "model_tag": model_tag,
                "attempts_per_goal": ATTEMPTS_PER_GOAL,
                "n_goals": n,
                "n_valid_attempt1": n_valid_attempt1,
                "n_valid_any_attempt": n_valid_any_attempt,
                "goals": results,
            },
            f,
            indent=2,
        )
    print(f"authored-scripts written to {out_path} (gitignored, not committed)", file=sys.stderr)

    for goal_id, r in results.items():
        status = "PASS" if r["first_valid_body"] is not None else "FAIL"
        print(f"  [{status}] {goal_id}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
