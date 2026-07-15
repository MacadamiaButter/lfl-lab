#!/usr/bin/env python3
"""
probe.py - the brainstorm-lane probe.

Measures whether a large local model can reliably AUTHOR valid, safe
lfl-terminal *scripts* - not whether it can drive a browser. For each goal in
goals.json, it asks the model (via a system prompt that teaches the fixed
verb set and the hard rules) to write a script body, then validates that body
through the REAL lfl-terminal validator (parseScriptBody(), reached by
shelling out to validate.js, which requires lfl-terminal's own
extension/content/registry.js unmodified - see that file's header). This
script never reimplements the validation rules itself, so there is zero
chance of this probe's notion of "valid" drifting from the product's.

This is a read-only inference client. It never mutates lfl-terminal, never
executes a proposed script against a browser, and never touches any port
except the one model endpoint it is pointed at.

Usage:
    export LFL_BRAINSTORM_ENDPOINT=http://<your-model-host>:<port>   # required
    export LFL_BRAINSTORM_API_KEY="$(cat /path/to/your/api-key)"     # required if the endpoint needs one
    python3 brainstorm/probe.py                 # --variant strict (default)
    python3 brainstorm/probe.py --variant naive  # stress-test variant, see below

Two system-prompt variants are built in, on purpose, to make "results depend
heavily on the system prompt" an observed comparison rather than an assumed
caveat:

  strict (default) - teaches the full verb list, spells out the index-address
    ban with the reason, and explicitly tells the model to reach for
    pause "..." whenever it would otherwise need to point at an element by
    number or position.
  naive - a much shorter prompt that lists step types (including click/select)
    without ever explaining why index-addressing is unsafe or nudging toward
    pause. Meant to surface real failures, not just report a clean 100%.

Both variables follow the same pattern as proxy/.env.example and
harness/README.md's LFL_MODEL_ENDPOINT: the real host and key live only in
your shell environment at run time, never in a tracked file. This process
never prints LFL_BRAINSTORM_API_KEY, and no output file records it.

Requires only the `requests` library (already used nowhere else in this
repo's Python code, but it is the standard, well-known choice - see
requirements note in brainstorm/README section of the top-level README).

Talks to a tailnet/LAN model host, which the ambient HTTP_PROXY/HTTPS_PROXY
(if any, e.g. a Tor proxy in some dev shells) would break - this script
disables proxying for its own requests unconditionally (`proxies={"http":
None, "https": None}`) regardless of what is set in the environment.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
GOALS_PATH = HERE / "goals.json"
VALIDATE_JS = HERE / "validate.js"
RESULTS_DIR = HERE / "results"  # gitignored - see .gitignore

REQUEST_TIMEOUT_S = 120
INTER_REQUEST_DELAY_S = 1.0  # the 35B is single-slot; be a polite sequential client

SYSTEM_PROMPT = """You are helping a user author a SCRIPT for a browser terminal extension called lfl-terminal.

A script is plain text, ONE STEP PER LINE. You may use ONLY the verbs listed below. Never invent a new verb, and never use any verb not on this list.

Allowed verbs (this is the complete list):
  go <destination>              navigate to a URL, domain, or site name
                                 example: go en.wikipedia.org
  open <link text>               follow a link by its VISIBLE TEXT, never by a number
                                 example: open "Contact us"
  search "<query>"               fill and submit the page's search box
                                 example: search "Eiffel Tower"
  scroll up                      scroll the page up
  scroll down                    scroll the page down
  fill <label> with "<text>"     fill a form field identified by its VISIBLE LABEL, never by a number
                                 example: fill email with "me@example.com"
  pause "<instruction>"          stop the script and hand control back to a human for ONE manual step
                                 example: pause "click the blue Submit button"

Use pause "<instruction>" for ANYTHING you cannot express with the verbs above: clicking a specific button, choosing an option from a dropdown, checking a checkbox, picking a search result by its position (first, third, ...), entering a password, or any other step that would need to point at a page element by a number or a position. Describe the manual action in plain words inside the quotes.

HARD RULES, always followed, no exceptions:
1. Only the verbs listed above. Never write "click <N>", "select <N>", a bare number on its own line, "fill <N> with ...", or "open <N>" - all of these address a page element by a numbered index, which is unsafe to replay later because the page can change between runs. If a step would need one of these, write a pause "<instruction>" step instead.
2. Never write "run <name>" - a script may not call another script.
3. Never write a game (snake, 2048, games, sl) or a fun-pack command (fortune, stats, theme, cowsay) - none of these are allowed inside a script.
4. At most 20 steps total.
5. Output ONLY the script body: one step per line, no step numbers, no markdown code fences, no headings, no explanation before or after. Just the lines of the script.

Now write the script body for the following goal."""

# The deliberately weaker stress-test variant (see module docstring). Lists
# click/select as available step types and never explains the index-address
# hazard or points the model at pause - this is what a less careful prompt
# author might ship, kept here to make the "results are prompt-sensitive"
# limitation an observed finding instead of an assumed caveat.
NAIVE_SYSTEM_PROMPT = """You are helping a user write a script for a browser automation terminal called lfl-terminal. A script is plain text, one step per line.

Available step types include things like:
  go <destination>
  open <link text or number>
  search "<query>"
  scroll up / scroll down
  fill <label or number> with "<text>"
  click <element>
  select <option>
  pause "<instruction>" for a manual step

Write the script body for the following goal. Output only the script lines, nothing else."""

SYSTEM_PROMPTS = {
    "strict": SYSTEM_PROMPT,
    "naive": NAIVE_SYSTEM_PROMPT,
}


def read_goals():
    with GOALS_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def strip_code_fence(text):
    """Defensive cleanup: some models wrap output in ``` fences despite being
    told not to. Strip a single leading/trailing fenced block if present;
    leave everything else untouched (this is cosmetic extraction, never
    validation - parseScriptBody() sees whatever text results from this)."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        # drop the opening fence line (``` or ```lang)
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


# A plain requests.post(..., proxies={"http": None, "https": None}) does NOT
# actually disable an ambient HTTP_PROXY/HTTPS_PROXY (e.g. a Tor proxy some
# dev shells export): requests treats an explicit None the same as "not set"
# and still merges in the environment's proxy. session.trust_env = False is
# what actually stops that merge - confirmed against the live endpoint while
# building this probe (an unqualified proxies={} dict failed with a
# ProxyError against the Tor tunnel). Kept as one session so every call in
# this process shares the same, verified-off proxy behavior.
_session = requests.Session()
_session.trust_env = False


def call_model(endpoint, api_key, goal_text, system_prompt):
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": goal_text},
        ],
        "temperature": 0.2,
        "max_tokens": 700,
    }
    resp = _session.post(
        f"{endpoint.rstrip('/')}/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=REQUEST_TIMEOUT_S,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def validate_body(body):
    """Shells out to validate.js, which requires lfl-terminal's own
    registry.js and calls the real parseScriptBody(). Never reimplemented
    here - see validate.js's header for why."""
    proc = subprocess.run(
        ["node", str(VALIDATE_JS)],
        input=json.dumps({"body": body}),
        capture_output=True,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        return {"ok": False, "reason": f"validate.js failed (exit {proc.returncode}): {proc.stderr.strip()}"}
    try:
        return json.loads(proc.stdout.strip())
    except json.JSONDecodeError as err:
        return {"ok": False, "reason": f"validate.js produced non-JSON output: {err}"}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--variant",
        choices=sorted(SYSTEM_PROMPTS.keys()),
        default="strict",
        help="which system-prompt variant to probe with (default: strict)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    system_prompt = SYSTEM_PROMPTS[args.variant]

    endpoint = os.environ.get("LFL_BRAINSTORM_ENDPOINT")
    if not endpoint:
        print(
            "LFL_BRAINSTORM_ENDPOINT is not set - point it at your model host, "
            "e.g. export LFL_BRAINSTORM_ENDPOINT=http://<your-model-host>:<port>",
            file=sys.stderr,
        )
        sys.exit(1)
    api_key = os.environ.get("LFL_BRAINSTORM_API_KEY", "")

    goals = read_goals()
    print(f"probing {len(goals)} goals ({args.variant} variant) against {endpoint} ...", file=sys.stderr)

    results = []
    for i, entry in enumerate(goals, start=1):
        goal_id = entry["id"]
        goal_text = entry["goal"]
        print(f"[{i}/{len(goals)}] {goal_id} ...", file=sys.stderr)
        try:
            raw_content = call_model(endpoint, api_key, goal_text, system_prompt)
        except requests.RequestException as err:
            results.append({
                "id": goal_id,
                "goal": goal_text,
                "raw_body": None,
                "valid": False,
                "reason": f"model request failed: {err}",
            })
            continue

        body = strip_code_fence(raw_content)
        verdict = validate_body(body)
        results.append({
            "id": goal_id,
            "goal": goal_text,
            "raw_body": body,
            "valid": bool(verdict.get("ok")),
            "reason": None if verdict.get("ok") else verdict.get("reason"),
            "step_count": verdict.get("stepCount"),
        })
        time.sleep(INTER_REQUEST_DELAY_S)

    n = len(results)
    n_ok = sum(1 for r in results if r["valid"])
    print(f"\n{n_ok}/{n} goals produced a script body that PASSED the real validator ({args.variant} variant).", file=sys.stderr)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RESULTS_DIR / f"run-{args.variant}-{ts}.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(
            {"variant": args.variant, "endpoint": endpoint, "n_goals": n, "n_valid": n_ok, "results": results},
            f,
            indent=2,
        )
    print(f"raw results written to {out_path} (gitignored, not committed)", file=sys.stderr)

    for r in results:
        status = "PASS" if r["valid"] else "FAIL"
        detail = "" if r["valid"] else f" - {r['reason']}"
        print(f"  [{status}] {r['id']}{detail}")


if __name__ == "__main__":
    main()
