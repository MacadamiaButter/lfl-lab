#!/usr/bin/env python3
"""harness/task_runner.py - TASK-SUCCESS BENCH, Phase B (EXECUTE).

Design doc: LFL-LAB-TASK-SUCCESS-BENCH-DESIGN.md (2026-07-17, approved,
kept outside this repo alongside the operator's other planning docs) - see
section 4 "The multi-cycle script runner" and section 6 "Metrics and
scoring".

Model-independent: this file never calls any LLM endpoint. It takes the
authored-scripts JSON that harness/author_tasks.py (Phase A) already
produced, seeds each goal's FIRST validator-passing script straight into the
real, unmodified extension's chrome.storage.local.lflScripts (same
service-worker-eval technique harness/runner.py's seed_dev_hooks()/
reset_rate_limit_state() already use for dev hooks and rate-limit state),
drives a real `run <name>` through the real extension with Playwright
keyboard input (closed shadow root - same reason runner.py's own header
explains), and scores the observed outcome against each goal's success
checks.

Imports shared driving helpers from harness/runner.py rather than
reimplementing them (get_service_worker, seed_dev_hooks,
reset_rate_limit_state, read_lfl_state, open_terminal, submit_command,
Navigated, ensure_http_server, port_open, check_extension_dir, CORPUS_DIR,
EXTENSION_DIR, PORT_A, PORT_B, HEADED, USER_DATA_DIR). runner.py already had
an `if __name__ == "__main__":` guard before this build touched it, so this
import is side-effect-free (no edit to runner.py was needed).

Uses its own Chrome profile-adjacent state only through the SAME
USER_DATA_DIR runner.py's P1 battery uses (imported, not redefined) -
deliberately reused rather than adding a second profile directory, so no
new .gitignore entry was needed either.

Why "seed into storage" instead of driving the in-extension `teach` flow -
see the design doc section 3 for the full reasoning (short version: keeps
:1238's owner bridge untouched, keeps authoring-vs-execution failure
attribution clean, and the wire-payload equivalence is already proven by
brainstorm/probe.py's shipped variant). Two manual teach-save-run smokes are
the disclosed mitigation - see harness/README.md.

Usage:
    python3 harness/author_tasks.py --tier fixture   # writes harness/results/authored-*.json
    python3 harness/task_runner.py --tier fixture --authored harness/results/authored-<...>.json

    python3 harness/task_runner.py --tier fixture --authored <path> --only shop-open-blue-widget

Output: harness/results/tasks-run-<modeltag>-<utcts>.json (gitignored, not
committed - see harness/README.md and .gitignore).
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
HARNESS_DIR = ROOT / "harness"
TASKS_DIR = HARNESS_DIR / "tasks"
SCENARIOS_PATH = TASKS_DIR / "task-scenarios.json"
RESOLVE_GO_JS = TASKS_DIR / "resolve_go.js"
RESULTS_DIR = HARNESS_DIR / "results"  # gitignored - see .gitignore

sys.path.insert(0, str(HARNESS_DIR))
from runner import (  # noqa: E402  (path insert must happen first)
    EXTENSION_DIR,
    HEADED,
    PORT_A,
    Navigated,
    check_extension_dir,
    ensure_http_server,
    open_terminal,
    read_lfl_state,
    reset_rate_limit_state,
    seed_dev_hooks,
    submit_command,
)
from runner import USER_DATA_DIR as CHROME_PROFILE_DIR  # noqa: E402

sys.path.insert(0, str(ROOT / "brainstorm"))
from probe import validate_body  # noqa: E402

POLL_INTERVAL_S = 0.15
NAV_SETTLE_MS = 400


# ---------------------------------------------------------------------------
# seeding - writes directly into chrome.storage.local.lflScripts via SW eval,
# NOT through setScript()/validateScriptBody() (design doc section 3/4): the
# whole point of Phase B is to prove the product's RUN-TIME re-validation
# (parseScriptBody + validateResolvedStep, both called again inside
# terminal.js's _handleRunCommand - see design doc section 2's ground-truth
# bullet on this) holds even when a script enters storage by a path other
# than the hand-typed `script new` UI.
# ---------------------------------------------------------------------------

def seed_script(sw, name, body, arity=0, uses_rest=False, step_count=None):
    """Merge {name: {body, arity, usesRest, stepCount}} into the extension's
    real chrome.storage.local.lflScripts, same storage key/shape
    createAliasStore() itself persists to (registry.js SCRIPT_KEY) - see
    that file's setScript(). Deliberately does NOT require `body` to have
    passed validate_body() first: a caller (this module's own S3-style
    seeded-bypass smoke) may intentionally seed a body that a real
    `script new` could never save, to prove `run` re-validates independently
    of what write-time would have checked - see module docstring."""
    if step_count is None:
        step_count = len([ln for ln in body.split("\n") if ln.strip() and not ln.strip().startswith("#")])
    sw.evaluate(
        "(entry) => new Promise((resolve) => chrome.storage.local.get(['lflScripts'], (res) => {"
        "  const scripts = (res && res.lflScripts && typeof res.lflScripts === 'object') ? res.lflScripts : {};"
        "  scripts[entry.name] = { body: entry.body, arity: entry.arity, usesRest: entry.usesRest, stepCount: entry.stepCount };"
        "  chrome.storage.local.set({ lflScripts: scripts }, resolve);"
        "}))",
        {"name": name, "body": body, "arity": arity, "usesRest": uses_rest, "stepCount": step_count},
    )


def unseed_script(sw, name):
    try:
        sw.evaluate(
            "(name) => new Promise((resolve) => chrome.storage.local.get(['lflScripts'], (res) => {"
            "  const scripts = (res && res.lflScripts && typeof res.lflScripts === 'object') ? res.lflScripts : {};"
            "  delete scripts[name];"
            "  chrome.storage.local.set({ lflScripts: scripts }, resolve);"
            "}))",
            name,
        )
    except Exception:  # noqa: BLE001 - best-effort cleanup only
        pass


def peek_task_queue(sw):
    """SW-side read of this run's per-tab termstate queue length, filtered
    by the 'termstate:' key prefix - same technique
    reset_rate_limit_state() (imported from runner.py) already uses for its
    own 'ratelimit:' prefix. Since each scenario runs in a fresh tab that is
    closed before the next one starts (the SW's tabs.onRemoved handler
    clears both prefixes for a closed tab - background/service-worker.js),
    at most one 'termstate:<tabId>' key is ever live at a time here."""
    try:
        res = sw.evaluate(
            "() => new Promise((resolve) => chrome.storage.session.get(null, (all) => {"
            "  const keys = Object.keys(all || {}).filter((k) => k.indexOf('termstate:') === 0);"
            "  if (keys.length === 0) { resolve(null); return; }"
            "  const st = all[keys[0]] || {};"
            "  resolve({ queueLen: (st.queue || []).length });"
            "}))"
        )
    except Exception:  # noqa: BLE001
        return None
    return res


# ---------------------------------------------------------------------------
# the multi-cycle watch loop (design doc section 4)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# nav-confirm safety guard (build-time addition, flagged as a deviation from
# the design doc's literal section 4 item 2 text - see harness/README.md's
# "deviations from the design doc" note and this build's own final report).
#
# S1 smoke evidence (2026-07-17, 4B/lfl-cohort-4b, shipped payload): given a
# fixture goal, the model authors almost every script starting with a `go
# <destination>` step even though the run already starts on the right page
# (the shipped payload gives the model no current-page context at all - see
# brainstorm/shipped_payload.js's own output). Two distinct real hazards
# follow, both first OBSERVED in that smoke, not hypothesized:
#   1. A literal-but-invented domain (e.g. `go products.go.com`) is a real,
#      resolvable-or-not hostname - approving its nav-confirm makes Chrome
#      open a REAL, DIRECT (not Tor-proxied - Playwright's launch args here
#      set no --proxy-server) connection to an arbitrary third party for a
#      "fixture tier" run that the design doc describes as self-contained /
#      zero external requests.
#   2. A non-domain-shaped destination (e.g. `go "products"`) fails the
#      literal resolution ladder in nav.js and falls through to the
#      extension's NAV-LANE MODEL FALLBACK - a real HTTP call to the
#      extension's hardcoded LFL_MODEL_ENDPOINT (127.0.0.1:1238, unrelated
#      to the 1236/1241 endpoints this build must never touch - see
#      harness/README.md). This still surfaces as `pendingNav`/
#      'awaiting-nav-confirm' (not `pendingProposal`/'awaiting-approval'),
#      with `modelResolved: true` - terminal.js's _confirmOrNavigate() sets
#      that flag exactly for this path (see that function's own comment).
#      Design doc section 9 sign-off E's fell_to_model policy ("Escapes any
#      model proposal during Phase B so execution stays model-independent")
#      applies here in spirit even though its section 4 prose only names
#      `pendingProposal` explicitly - a model-resolved nav destination is
#      just as much "the script fell into the model lane" as an `ask` step
#      is, and approving it blind would also break "Phase B never calls any
#      LLM endpoint" (this file's own module docstring).
#
# Policy: a modelResolved pendingNav is ALWAYS rejected (Escape), scored
# fell_to_model - never approved, never counted as a nav_confirm (no human
# analogue gave that approval). A non-modelResolved pendingNav is approved
# ONLY if its origin is on the fixed per-tier allowlist below; otherwise it
# is rejected (Escape) and the run is scored `halted`, with the evidence
# explicit that this was a harness safety policy, not a product-side halt -
# see classify()'s docstring and the "checks"/"evidence" shape in the
# committed RESULTS-TASKS.md.
REALSITE_ALLOWED_ORIGIN_SUFFIX = ".wikipedia.org"
REALSITE_ALLOWED_EXACT_ORIGINS = {"https://wikipedia.org"}


def nav_origin_allowed(origin, tier):
    if not origin:
        return False
    if tier == "fixture":
        # Fixture tier stays local http on 127.0.0.1 by design - the
        # self-contained corpus server never speaks https, so this exact
        # match is intentionally NOT scheme-pinned to https (see FIX 3's
        # scope note below, and RESULTS-TASKS.md's LIMITATIONS).
        return origin == f"http://127.0.0.1:{PORT_A}"
    if tier == "realsite":
        # FIX 3 (verify-pass correction): the suffix check below is a plain
        # string endswith() on the ORIGIN, which previously did not pin the
        # scheme - "http://en.wikipedia.org" ends with ".wikipedia.org" just
        # as much as "https://en.wikipedia.org" does, so a plaintext-HTTP
        # origin would have been approved. Require https explicitly first;
        # only then does the suffix/exact-origin check below run.
        if not origin.startswith("https://"):
            return False
        return origin in REALSITE_ALLOWED_EXACT_ORIGINS or origin.endswith(REALSITE_ALLOWED_ORIGIN_SUFFIX)
    return False


def wait_for_mode(page, target_modes, timeout_s):
    deadline = time.monotonic() + timeout_s
    state = None
    while time.monotonic() < deadline:
        try:
            state = read_lfl_state(page)
        except Navigated:
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(NAV_SETTLE_MS)
            continue
        if state and state.get("mode") in target_modes:
            return state
        time.sleep(POLL_INTERVAL_S)
    return state


def watch_run(page, sw, seq0, timeout_s, tier):
    """Drives the poll loop described in design doc section 4 item 2 (plus
    the nav-confirm safety guard added above). Returns a dict: {state,
    nav_confirms, steps_dispatched, last_result, final_url}.

    `state` is one of: completed, halted, paused, fell_to_model, timeout.
    (`invalid_author` and `harness_error` are decided by the caller, not
    here - this function only ever runs once a script is already seeded and
    approved.)

    steps_dispatched counts DISTINCT (ok, message) lastResult snapshots seen
    across the run - a change-detector on the same field _settle() writes on
    every step dispatch, robust to the fact that a navigating final step's
    lastResult resets to null on the freshly-injected document (a brand new
    Terminal() instance per page load - see terminal.js's _lastResult=null
    constructor default) and to the queue itself being cleared to 0 on a
    halt (so the SW-side queue length alone cannot disambiguate "completed"
    from "halted mid-way" - only lastResult.ok can, which is why this
    function checks it directly rather than back-computing from queue
    length)."""
    started = False
    nav_confirms = 0
    steps_dispatched = 0
    last_seen = None
    deadline = time.monotonic() + timeout_s
    state = None

    while time.monotonic() < deadline:
        try:
            state = read_lfl_state(page)
        except Navigated:
            started = True
            try:
                page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(NAV_SETTLE_MS)
            continue

        if state is None:
            time.sleep(POLL_INTERVAL_S)
            continue

        if state.get("seq") != seq0:
            started = True

        last_result = state.get("lastResult")
        if last_result is not None:
            marker = (last_result.get("ok"), last_result.get("message"))
            if marker != last_seen:
                last_seen = marker
                steps_dispatched += 1

        mode = state.get("mode")
        pending_nav = state.get("pendingNav")
        pending_proposal = state.get("pendingProposal")

        if pending_nav is not None and mode == "awaiting-nav-confirm":
            if pending_nav.get("modelResolved"):
                # Nav-lane model fallback (a real call to the extension's
                # hardcoded :1238 already happened to produce this
                # destination) - never approved, same posture as an `ask`
                # pendingProposal. See the guard block's own comment above.
                page.keyboard.press("Escape")
                time.sleep(0.2)
                return {
                    "state": "fell_to_model",
                    "nav_confirms": nav_confirms,
                    "steps_dispatched": steps_dispatched,
                    "last_result": last_result,
                    "final_url": page.url,
                    "note": f"go destination required nav-lane model resolution: {pending_nav.get('url')}",
                }
            if not nav_origin_allowed(pending_nav.get("origin"), tier):
                page.keyboard.press("Escape")
                time.sleep(0.2)
                return {
                    "state": "halted",
                    "nav_confirms": nav_confirms,
                    "steps_dispatched": steps_dispatched,
                    "last_result": last_result,
                    "final_url": page.url,
                    "note": (
                        f"harness safety policy blocked an off-allowlist navigation "
                        f"(tier={tier}, attempted origin={pending_nav.get('origin')!r}, "
                        f"url={pending_nav.get('url')!r}) - not a product-side halt"
                    ),
                }
            page.keyboard.press("Enter")
            nav_confirms += 1
            time.sleep(0.2)
            continue

        if pending_proposal is not None and mode == "awaiting-approval":
            page.keyboard.press("Escape")
            time.sleep(0.2)
            return {
                "state": "fell_to_model",
                "nav_confirms": nav_confirms,
                "steps_dispatched": steps_dispatched,
                "last_result": last_result,
                "final_url": page.url,
            }

        if (
            last_result
            and last_result.get("ok") is True
            and isinstance(last_result.get("message"), str)
            and last_result["message"].lower().startswith("paused")
        ):
            return {
                "state": "paused",
                "nav_confirms": nav_confirms,
                "steps_dispatched": steps_dispatched,
                "last_result": last_result,
                "final_url": page.url,
            }

        if started and mode == "idle" and pending_nav is None and pending_proposal is None:
            qinfo = peek_task_queue(sw)
            queue_len = qinfo["queueLen"] if qinfo else 0
            if queue_len == 0:
                if last_result is not None and last_result.get("ok") is False:
                    return {
                        "state": "halted",
                        "nav_confirms": nav_confirms,
                        "steps_dispatched": steps_dispatched,
                        "last_result": last_result,
                        "final_url": page.url,
                    }
                return {
                    "state": "completed",
                    "nav_confirms": nav_confirms,
                    "steps_dispatched": steps_dispatched,
                    "last_result": last_result,
                    "final_url": page.url,
                }

        time.sleep(POLL_INTERVAL_S)

    return {
        "state": "timeout",
        "nav_confirms": nav_confirms,
        "steps_dispatched": steps_dispatched,
        "last_result": state.get("lastResult") if state else None,
        "final_url": page.url,
    }


def run_seeded_script(page, sw, name, run_args, timeout_s, tier):
    """Types `run <name> [args...]`, waits for the plan-preview card
    (mode == 'awaiting-script-run' - design doc section 4 item 1), approves
    with Enter, then hands off to watch_run(). Returns watch_run()'s dict, or
    a synthetic {'state': 'harness_error', ...} if the plan-preview card
    never showed up (e.g. the seeded body was rejected by `run`'s own
    re-parse before ever reaching the approval card - a real, honest outcome
    for a badly malformed seed, exactly what the seeded-bypass smoke
    (harness/README.md's S3) expects to observe, not a harness bug).

    Shared by run_one_scenario() below (the real Phase B pipeline, which
    only ever seeds a validator-passing body) and any ad hoc smoke driver
    that wants to seed a hand-written or deliberately-malformed body through
    the exact same real code path - see module docstring."""
    open_terminal(page)
    cmd_parts = [name] + [f'"{a}"' if " " in a else a for a in (run_args or [])]
    submit_command(page, "run " + " ".join(cmd_parts))
    state = wait_for_mode(page, ("awaiting-script-run",), min(15, timeout_s))
    if not state or state.get("mode") != "awaiting-script-run":
        # `run` itself rejected the seeded script (bad name, re-parse
        # failure, arity mismatch, ...) before ever showing a plan preview -
        # state (if any) already carries the rejection's lastResult.
        return {
            "state": "harness_error",
            "nav_confirms": 0,
            "steps_dispatched": 0,
            "last_result": (state or {}).get("lastResult") if state else None,
            "final_url": page.url,
            "note": "run command never reached awaiting-script-run (seed rejected at parse time, see last_result)",
        }
    seq0 = state.get("seq")
    page.keyboard.press("Enter")
    return watch_run(page, sw, seq0, timeout_s, tier)


# ---------------------------------------------------------------------------
# success checks (design doc section 5)
# ---------------------------------------------------------------------------

def check_url_contains(page, value):
    return value in page.url


def check_text_visible(page, value):
    try:
        if page.get_by_text(value, exact=False).count() > 0:
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        return value in (page.content() or "")
    except Exception:  # noqa: BLE001
        return False


def check_field_value(page, selector, expected):
    try:
        actual = page.locator(selector).input_value(timeout=2000)
    except Exception as e:  # noqa: BLE001
        return False, f"<eval error: {e}>"
    return actual == expected, actual


def evaluate_checks(page, checks):
    rows = []
    for c in checks:
        ctype = c.get("type")
        try:
            if ctype == "url_contains":
                ok = check_url_contains(page, c["value"])
                rows.append({"type": ctype, "value": c["value"], "ok": ok})
            elif ctype == "text_visible":
                ok = check_text_visible(page, c["value"])
                rows.append({"type": ctype, "value": c["value"], "ok": ok})
            elif ctype == "field_value":
                ok, observed = check_field_value(page, c["selector"], c["value"])
                rows.append({"type": ctype, "selector": c["selector"], "value": c["value"], "observed": observed, "ok": ok})
            else:
                rows.append({"type": ctype, "ok": False, "error": f"unknown check type: {ctype}"})
        except Exception as e:  # noqa: BLE001 - one bad check must not kill the row
            rows.append({"type": ctype, "ok": False, "error": f"{e.__class__.__name__}: {e}"})
    return rows


# ---------------------------------------------------------------------------
# go-step pre-classification (verify-pass FIX 1a) - shells out to
# harness/tasks/resolve_go.js, which requires the REAL, unmodified
# lfl-terminal extension/content/nav.js and calls its real
# resolveGoLadder() - never reimplemented here, same zero-drift rule
# validate_body()/build_shipped_payload() (brainstorm/probe.py) already
# apply to registry.js/service-worker.js. See resolve_go.js's own header for
# the full misattribution this closes: a `go <arg>` step whose arg is
# non-empty and not a literal URL/domain ALWAYS falls to
# resolveGoLadder()'s step 3 (needsNavLane: true), at which point
# terminal.js's _handleGo() makes a real NAV_LLM_REQUEST call to :1238 and
# prints back whatever reason the model gave - so a `halted` outcome on such
# a step is model-authored, not a deterministic ladder rejection, and must be
# bucketed fell_to_model instead.
# ---------------------------------------------------------------------------

_GO_STEP_RE = re.compile(r'^go\s+(.*)$', re.IGNORECASE)


def parse_body_steps(body):
    """Same non-blank/non-comment line filter seed_script() already uses for
    its own step_count fallback, so a 1-based index into this list lines up
    with the step numbering the product's own error messages use (e.g.
    "step 1: ...")."""
    return [ln.strip() for ln in body.split("\n") if ln.strip() and not ln.strip().startswith("#")]


def extract_go_arg(step_line):
    """Returns the text after `go ` with one layer of surrounding quotes
    stripped if present (`go "products"` -> `products`), or None if this
    line is not a `go` step. Only used to pick WHICH arg to hand to the real
    resolver below - the resolver, not this function, decides what the arg
    means."""
    m = _GO_STEP_RE.match(step_line)
    if not m:
        return None
    arg = m.group(1).strip()
    if len(arg) >= 2 and arg[0] == arg[-1] and arg[0] in ('"', "'"):
        arg = arg[1:-1]
    return arg


def resolve_go_arg(arg, cache):
    """Shells out to resolve_go.js (real nav.js resolveGoLadder()), cached
    by arg string within a single run so a repeated arg (e.g. "products"
    appearing in more than one script) costs one node process, not one per
    occurrence."""
    if arg in cache:
        return cache[arg]
    try:
        proc = subprocess.run(
            ["node", str(RESOLVE_GO_JS)],
            input=json.dumps({"arg": arg}),
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            verdict = {"ok": False, "reason": f"resolve_go.js failed (exit {proc.returncode}): {proc.stderr.strip()}"}
        else:
            verdict = json.loads(proc.stdout.strip())
    except Exception as e:  # noqa: BLE001 - a pre-classification failure must not kill the run
        verdict = {"ok": False, "reason": f"resolve_go.js invocation error: {e.__class__.__name__}: {e}"}
    cache[arg] = verdict
    return verdict


def classify_go_steps(body, cache):
    """Returns {1-based step index: resolve_go.js verdict} for every `go`
    step in body - non-`go` steps are simply absent from the dict."""
    out = {}
    for i, line in enumerate(parse_body_steps(body), start=1):
        arg = extract_go_arg(line)
        if arg is None:
            continue
        out[i] = resolve_go_arg(arg, cache)
    return out


def _is_harness_policy_halt(run_result):
    """True only for the nav-confirm-allowlist rejection branch in
    watch_run() above, which tags its own `note` explicitly - distinct from
    a genuine idle/failed-lastResult halt (note is None in that case), so
    this never touches model-authored message text to decide anything."""
    return "harness safety policy" in (run_result.get("note") or "")


# ---------------------------------------------------------------------------
# bucket/scoring (design doc section 6)
# ---------------------------------------------------------------------------

def classify(run_state, expect_pause, checks_ok):
    """Returns (success: bool, bucket: str or None). bucket is None only
    when success is True. See harness/README.md's task-success section for
    the same table in prose, kept in sync with this function on purpose."""
    if run_state == "timeout":
        return False, "timeout"
    if run_state == "harness_error":
        return False, "harness_error"
    if run_state == "fell_to_model":
        return False, "fell_to_model"
    if run_state == "halted":
        return False, "halted"
    if run_state == "paused":
        if not expect_pause:
            return False, "pause_unexpected"
        return (True, None) if checks_ok else (False, "wrong_plan")
    if run_state == "completed":
        if expect_pause:
            # Should have parked at a pause step but ran to completion
            # instead - a plan-shape miss, not an execution halt.
            return False, "wrong_plan"
        return (True, None) if checks_ok else (False, "wrong_plan")
    return False, "harness_error"


# ---------------------------------------------------------------------------
# per-scenario orchestration
# ---------------------------------------------------------------------------

def run_one_scenario(context, sw, scenario, body, timeout_s_override=None, go_resolve_cache=None):
    name = scenario["id"]
    timeout_s = timeout_s_override or scenario.get("timeout_s", 60)
    row = {"id": scenario["id"], "tier": scenario.get("tier"), "expect_pause": bool(scenario.get("expect_pause"))}
    t0 = time.monotonic()

    verdict = validate_body(body)
    seed_script(
        sw, name, body,
        arity=verdict.get("arity") or 0,
        uses_rest=bool(verdict.get("usesRest")),
        step_count=verdict.get("stepCount"),
    )

    # FIX 1a: pre-classify every `go` step's argument through the real
    # resolveGoLadder() BEFORE the run, so a halt that lands on one of them
    # can be correctly attributed below regardless of what message text the
    # product/model happened to print.
    go_steps = classify_go_steps(body, go_resolve_cache if go_resolve_cache is not None else {})

    page = context.new_page()
    try:
        start_url = f"http://127.0.0.1:{PORT_A}/{scenario['start_page']}"
        row["start_url"] = start_url
        page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(500)

        run_result = run_seeded_script(page, sw, name, scenario.get("run_args") or [], timeout_s, scenario.get("tier"))

        row["state"] = run_result["state"]
        row["nav_confirms"] = run_result["nav_confirms"]
        row["steps_executed"] = run_result["steps_dispatched"]
        row["evidence"] = {
            "final_url": run_result.get("final_url"),
            "last_result": run_result.get("last_result"),
            "note": run_result.get("note"),
        }

        checks = scenario.get("success") or []
        if run_result["state"] not in ("timeout", "harness_error"):
            row["checks"] = evaluate_checks(page, checks)
        else:
            row["checks"] = []
        checks_ok = bool(row["checks"]) and all(c.get("ok") for c in row["checks"])

        success, bucket = classify(run_result["state"], row["expect_pause"], checks_ok)

        # FIX 1a (verify-pass correction, see classify_go_steps() above): a
        # genuine product-side `halted` outcome (not the harness's own
        # nav-confirm-allowlist rejection) whose failing step was a `go
        # <arg>` step the REAL ladder reports needsNavLane for is, by
        # construction, the result of a live nav-lane model call that
        # declined to navigate - reclassify it fell_to_model instead of
        # halted. steps_dispatched (1-based) is the step that produced the
        # halting lastResult - see watch_run()'s own change-detector.
        if bucket == "halted" and not _is_harness_policy_halt(run_result):
            step_idx = max(1, run_result.get("steps_dispatched") or 1)
            go_verdict = go_steps.get(step_idx)
            if go_verdict and go_verdict.get("needsNavLane"):
                bucket = "fell_to_model"
                success = False
                extra_note = "nav-lane model call occurred (go arg is non-literal); abort reason is model-authored"
                row["evidence"]["note"] = (
                    f"{row['evidence']['note']}; {extra_note}" if row["evidence"].get("note") else extra_note
                )

        # FIX 2: end-state-only success checks are gameable on path-dependent
        # goals (a degenerate 1-step script can reach the right end state by
        # accident). If the scenario declares min_steps_executed, enforce it
        # at scoring time: fewer real steps than that floor demotes an
        # otherwise-successful row to wrong_plan, even though the end-state
        # checks passed - see task-scenarios.json's shop-open-item-back-to-products
        # and README's task-success section for the field's documentation.
        min_steps = scenario.get("min_steps_executed")
        if success and isinstance(min_steps, int) and row["steps_executed"] < min_steps:
            success = False
            bucket = "wrong_plan"
            row["checks"].append({
                "type": "min_steps_executed",
                "value": min_steps,
                "observed": row["steps_executed"],
                "ok": False,
            })

        row["success"] = success
        row["bucket"] = bucket
    except Exception as e:  # noqa: BLE001 - one bad scenario must not kill the run
        row["state"] = "harness_error"
        row["success"] = False
        row["bucket"] = "harness_error"
        row["checks"] = []
        row["evidence"] = {"error": f"{e.__class__.__name__}: {e}"}
    finally:
        row["wall_s"] = round(time.monotonic() - t0, 2)
        unseed_script(sw, name)
        try:
            page.close()
        except Exception:  # noqa: BLE001
            pass

    return row


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def read_scenarios(tier, only):
    scenarios = json.loads(SCENARIOS_PATH.read_text())
    if tier != "all":
        scenarios = [s for s in scenarios if s.get("tier") == tier]
    if only:
        wanted = set(only)
        scenarios = [s for s in scenarios if s["id"] in wanted]
    return scenarios


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tier", choices=["fixture", "realsite", "all"], default="fixture")
    parser.add_argument("--authored", required=True, help="path to a harness/results/authored-*.json from author_tasks.py")
    parser.add_argument("--only", action="append", default=None, help="scenario id to run (repeatable); default: all in --tier")
    return parser.parse_args()


def main():
    args = parse_args()
    check_extension_dir()

    authored_path = Path(args.authored)
    authored = json.loads(authored_path.read_text())
    goals = authored.get("goals", authored)  # tolerate either the full wrapper or a bare {id: {...}} map
    model_tag = authored.get("model_tag", "unknown")

    scenarios = read_scenarios(args.tier, args.only)
    if not scenarios:
        print("no scenarios matched --tier/--only", file=sys.stderr)
        return 1

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    procs = [ensure_http_server(PORT_A)]
    results = []
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(CHROME_PROFILE_DIR),
                headless=not HEADED,
                args=[
                    f"--disable-extensions-except={EXTENSION_DIR}",
                    f"--load-extension={EXTENSION_DIR}",
                    "--no-first-run",
                    "--no-sandbox",
                ],
            )
            sw = seed_dev_hooks(context)
            go_resolve_cache = {}  # shared across scenarios within this run - see resolve_go_arg()

            for i, scenario in enumerate(scenarios, start=1):
                goal_id = scenario["id"]
                entry = goals.get(goal_id)
                body = entry.get("first_valid_body") if entry else None
                if not body:
                    row = {
                        "id": goal_id, "tier": scenario.get("tier"),
                        "expect_pause": bool(scenario.get("expect_pause")),
                        "state": "invalid_author", "success": False, "bucket": "invalid_author",
                        "nav_confirms": 0, "steps_executed": 0, "checks": [], "wall_s": 0.0,
                        "evidence": {"note": "no validator-passing script from Phase A for this goal"},
                    }
                    results.append(row)
                    print(f"[{i:02d}/{len(scenarios)}] {goal_id:36s} -> invalid_author (no authored script)")
                    continue

                reset_rate_limit_state(sw)
                row = run_one_scenario(context, sw, scenario, body, go_resolve_cache=go_resolve_cache)
                results.append(row)
                status = "SUCCESS" if row.get("success") else f"FAIL({row.get('bucket')})"
                print(f"[{i:02d}/{len(scenarios)}] {goal_id:36s} -> {status}  (state={row.get('state')}, nav_confirms={row.get('nav_confirms')}, steps={row.get('steps_executed')}, {row.get('wall_s')}s)")

            context.close()
    finally:
        for proc in procs:
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    proc.kill()

    # FIX 4a: design doc section 6 - harness_error is "excluded from rates,
    # counted" - it never belonged in the task_success denominator (a harness
    # bug on one goal should not silently shrink the observed rate the way a
    # real product failure does). n_total stays the full row count for
    # reference; n_rated is the denominator task_success is actually over.
    n_total = len(results)
    n_harness_error = sum(1 for r in results if r.get("bucket") == "harness_error")
    n_rated = n_total - n_harness_error
    n_success = sum(1 for r in results if r.get("success"))
    buckets = {}
    for r in results:
        b = r.get("bucket")
        if b:
            buckets[b] = buckets.get(b, 0) + 1

    timestamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    safe_tag = "".join(c if (c.isalnum() or c in "-_.") else "-" for c in model_tag)
    out_path = RESULTS_DIR / f"tasks-run-{safe_tag}-{timestamp}.json"
    out = {
        "timestamp_utc": timestamp,
        "tier": args.tier,
        "authored_from": str(authored_path),
        "model_tag": model_tag,
        "extension_dir": str(EXTENSION_DIR),
        "n_total": n_total,
        "n_harness_error": n_harness_error,
        "n_rated": n_rated,
        "n_success": n_success,
        "buckets": buckets,
        "results": results,
    }
    out_path.write_text(json.dumps(out, indent=2))

    print("\n=== summary ===")
    print(f"task_success: {n_success}/{n_rated}  (n_total={n_total}, harness_error excluded: {n_harness_error})")
    for b, c in sorted(buckets.items()):
        print(f"  {b}: {c}")
    print(f"results written to {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
