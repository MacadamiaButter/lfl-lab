# RESULTS-TASKS - task-success bench (goal -> authored script -> real execution -> observed outcome)

Design doc: `LFL-LAB-TASK-SUCCESS-BENCH-DESIGN.md` (2026-07-17, approved,
kept outside this repo with the operator's other planning docs). Regenerate/
extend this yourself with `harness/author_tasks.py` (Phase A) then
`harness/task_runner.py` (Phase B) - see `harness/README.md`'s task-success
section for the exact commands, including the `--condition` flag described
below.

Read the LIMITATIONS section as part of the result, same posture as
`harness/RESULTS.md` and `harness/RESULTS-AB.md` - this bench's honesty is
its credibility, not a footnote to it.

## Methodology

Phase A (AUTHOR, no browser) makes 2 authoring attempts per goal against the
real shipped wire payload; Phase B (EXECUTE, real extension, headed
Playwright) seeds the first validator-passing script and drives it to a
terminal state, then runs the goal's own success checks. See
`harness/README.md`'s task-success section for the full mechanics
(go-step pre-classification, the nav-confirm origin allowlist,
`min_steps_executed`) - this section covers only what is new tonight.

**Two measured conditions, same goal set, same models, same corpus.**
`harness/author_tasks.py --condition baseline` authors each goal's text
verbatim (the design doc's original convention). `--condition on-site`
authors the exact same goal text with one fixed line prepended:

```
You are already on the correct site.
```

(`ON_SITE_PREAMBLE` in `harness/author_tasks.py`.) This is owner-approved
follow-up work to the go-preamble finding first observed in the original
single-condition 4B run (see "Mechanism" below): the shipped payload sends
only `{"goal": "<text>"}` to the model, with no URL, no page title, no
signal that a `teach` session is already sitting on the relevant page. A
model that always opens with a `go <destination>` step under that payload
could mean either of two very different things - "this model always invents
a destination regardless of context" or "this model follows whatever
context the goal happens to state, and the shipped payload just never gives
it any." The on-site condition isolates the second question: it changes
nothing about the corpus, the extension, or the wire format itself - it is
a goal-text manipulation only, run through the exact same unmodified
authoring and execution pipeline. **The shipped payload sent to the real
product still carries no page context in either condition** - on-site
proves what the model does when it is TOLD there is no navigation to do,
not what the shipped product tells it by default. That gap is real and
stays open; see LIMITATIONS.

Two models, run through both conditions the same night, same corpus, same
harness build:

- **4B** - `lfl-cohort-4b`, `http://127.0.0.1:1241` (iGPU, keyless, local).
- **36B (fleet)** - the fleet machine's currently-loaded ~36B model, on the
  fleet's tailnet `:1236` endpoint (this is the previously TBD "35B fleet"
  row; the fleet's loaded model has changed since that placeholder was
  written, roughly a 9x parameter jump from the 4B). The exact model tag
  and tailnet address are intentionally kept out of this public doc - they
  are two of this repo's own `tests/check_no_leaks.sh` patterns - and live
  only in the gitignored raw JSON's `model_tag`/`endpoint` fields.

Four authoring runs (`authored-<model>-<condition>-<ts>.json`) and four
Phase B execution runs (`tasks-run-<model>-<ts>.json`) were completed
2026-07-17, forming a full 2x2 (model x condition). Raw files are in
`harness/results/` (gitignored, not committed) - regenerate with the
commands in `harness/README.md`.

## Canonical results: the 2x2 (model x condition)

**Headline.** Both models authored 14/14 valid scripts on attempt 1 in all
four cells (see "authored_valid, precisely" below - this bench's authoring
validity metric is saturated for both models on this corpus and is not
where the interesting result lives). The **go-first-step rate is identical
between the two models within each condition** despite the ~9x parameter
gap: 14/14 for both models under baseline, 9/14 for both models under
on-site. The on-site condition produced this bench's **first task
successes** (2/14 for 4B, 3/14 for 36B (fleet)) - the earlier
single-condition baseline run never got a chance to show anything past the
go-preamble failure. See "Findings" below for what these numbers mean and
do not mean.

| model | condition | authored_valid (attempt1/any) | go-first-step | task_success | wrong_plan | halted | fell_to_model | pause_unexpected | timeout | harness_error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 4B (`lfl-cohort-4b`, `:1241`) | baseline | 14/14 / 14/14 | 14/14 | 0/14 | 0 | 10 | 4 | 0 | 0 | 0 |
| 4B (`lfl-cohort-4b`, `:1241`) | on-site | 14/14 / 14/14 | 9/14 | 2/14 | 3 | 6 | 3 | 0 | 0 | 0 |
| 36B (fleet, `:1236`) | baseline | 14/14 / 14/14 | 14/14 | 0/14 | 0 | 5 | 9 | 0 | 0 | 0 |
| 36B (fleet, `:1236`) | on-site | 14/14 / 14/14 | 9/14 | 3/14 | 2 | 0 | 9 | 0 | 0 | 0 |
| 4B (`lfl-cohort-4b`, `:1241`) | realsite | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 36B (fleet, `:1236`) | realsite | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

`go-first-step` is counted directly from each authoring run's
`first_valid_body` - the fraction of the 14 goals whose first script line
begins with the `go` verb. `task_success` is `n_success/n_rated` (0
`harness_error` rows in all four cells this run, so `n_rated = 14`
throughout - see "denominator, precisely" below). Raw files:
`authored-lfl-cohort-4b-baseline-20260717T084927Z.json` ->
`tasks-run-lfl-cohort-4b-20260717T085524Z.json`;
`authored-lfl-cohort-4b-on-site-20260717T085219Z.json` ->
`tasks-run-lfl-cohort-4b-20260717T085542Z.json`; and the matching
36B (fleet) baseline/on-site authored+run JSON pairs, same
`harness/results/` directory, same 08:53-08:57Z window (filenames omitted
here on purpose - they embed the real fleet model tag, which is one of
this repo's own `tests/check_no_leaks.sh` patterns; see the gitignored
files directly, or regenerate with the commands in `harness/README.md`)
(all gitignored, not committed).

**Per-goal outcome, all four cells** (bucket, or `SUCCESS` for a row where
`success: true`; taken verbatim from each raw run's `bucket`/`success`
fields, never invented):

| goal id | 4B baseline | 4B on-site | 36B baseline | 36B on-site |
| --- | --- | --- | --- | --- |
| shop-open-blue-widget | halted | fell_to_model | fell_to_model | fell_to_model |
| shop-open-red-gadget | fell_to_model | halted | fell_to_model | fell_to_model |
| shop-open-green-gizmo | fell_to_model | halted | fell_to_model | fell_to_model |
| shop-open-yellow-widget | halted | fell_to_model | fell_to_model | fell_to_model |
| shop-search-open-blue | halted | halted | fell_to_model | fell_to_model |
| shop-search-open-red | halted | halted | fell_to_model | fell_to_model |
| shop-search-open-green | halted | halted | fell_to_model | fell_to_model |
| shop-search-third-pause | halted | halted | fell_to_model | fell_to_model |
| signup-contact-pause | halted | **SUCCESS** (paused) | halted | **SUCCESS** (paused) |
| signup-newsletter-pause | halted | wrong_plan | halted | wrong_plan |
| signup-message-pause | fell_to_model | wrong_plan | halted | wrong_plan |
| shop-scroll-item | fell_to_model | **SUCCESS** | halted | **SUCCESS** |
| shop-open-item-back-to-products | halted | fell_to_model | fell_to_model | fell_to_model |
| shop-open-signup | halted | wrong_plan | halted | **SUCCESS** |

## Findings

**(a) The go-first-step rate is identical across the ~9x model jump, in
both conditions - the go-preamble is a property of the shipped wire
format, not model scale.** Baseline: 14/14 for both 4B and 36B (fleet).
On-site: 9/14 for both. A 9x parameter increase changed neither number. The
mechanism (see "Mechanism" below) is that the shipped payload gives the
model nothing to ground on - a small model and a much larger one presented
with the same context-free goal text default to the same navigational
guess-first behavior at almost exactly the same rate. This is evidence
against "a bigger model would just know it's already on the site" and
evidence for "the payload needs to say so."

**(b) The on-site condition produced this bench's first task successes,
but both models still opened with a navigation guess on most goals despite
being told explicitly not to.** 9 of 14 goals per model still start with a
`go` step under on-site - only the 5 goals whose text is unambiguously
non-navigational (`fill`/`open`/`scroll`-shaped goals: the three signup
goals, `shop-scroll-item`, `shop-open-signup`) got a preamble-honoring
first step from both models. The 8 shop-goal-with-shop-language goals
(`shop-open-*`, `shop-search-*`) kept the `go` guess for both models even
with the on-site sentence sitting directly in front of the goal text. An
explicit stated fact in the prompt is not enough to fully override the
learned "authoring a script always starts with a destination" prior on
this corpus.

**(c) Differential failure signature: 4B tends to invent literal fake
domains, 36B (fleet) tends toward vague non-literal destinations.**
Baseline: 4B's 14 `go`-first scripts split 10 `halted` (harness-allowlist
rejection of a literal-looking domain) / 4 `fell_to_model` (needsNavLane,
a real live `:1238` call); the fleet 36B split the other way, 5 `halted`
/ 9 `fell_to_model`. The same skew holds among the on-site condition's
9 `go`-first rows per model: 4B 6 `halted` / 3 `fell_to_model`;
36B (fleet) 0 `halted` / 9 `fell_to_model`. Real quoted `go` arguments
from the authored JSONs:
- 4B, literal-domain-shaped (parsed as a literal URL by `resolveGoLadder()`,
  then rejected by this harness's own nav-confirm allowlist - never reaches
  the model a second time): `go products.page.com`, `go product.com`,
  `go signuptemplate.com`, `go productstore.com`, `go signuptoday.com`.
- 36B (fleet), vague/non-literal (no dot, or not URL-shaped, so
  `resolveGoLadder()` returns `needsNavLane: true` and the extension makes
  a real nav-lane call to `:1238`): `go products page`, `go products`
  (used on 9 of its 14 baseline goals, near-verbatim).
- Both models also produce the other pattern sometimes (4B: `go "products"`,
  `go "green gizmo store"`, both `fell_to_model`; 36B (fleet):
  `go example.com`, `go lfl-terminal.com`, both `halted`) - this is a skew,
  not a hard rule, and the skew held across both conditions tonight.

**(d) `wrong_plan` appears only under on-site - execution exposes
authoring shallowness that authoring validity cannot.** 0 `wrong_plan` rows
in either baseline cell (nothing got past the go-preamble far enough to be
scored on plan quality). Under on-site, 5 `wrong_plan` rows appeared across
both models (3 for 4B, 2 for 36B (fleet)), all real execution failures
of scripts that had already passed `parseScriptBody()`: `signup-newsletter-
pause` and `signup-message-pause` ran to `completed` for both models
instead of pausing before submit (the goal asks for a pause; `classify()`
demotes a completed run on an `expect_pause` goal to `wrong_plan`
regardless of what the checks say). `signup-message-pause` additionally
fails its own `field_value` check for both models (`observed: ""` against
the `#signup-message` selector) - both models authored a script that never
actually lands text in the message field. `shop-open-signup` (4B only)
authored a plausible-looking single `open "Sign up for updates"` step, but
scored `wrong_plan` because the `url_contains signup.html` check read
`false` against the captured `final_url` (still `shop.html`) even though
the step's own `last_result` says `"opening \"Sign up for updates\" ->
.../signup.html"` - consistent with the async-navigation-vs-check-timing
class of issue this repo's LIMITATIONS and README's "Honesty notes"
already disclose elsewhere, not a new mechanism. None of this was visible
at authoring-validity time; only real execution against real checks caught
it.

**(e) The paused-success case.** `signup-contact-pause` is the one goal
that both models scripted correctly enough to succeed under on-site: `fill
name with "Jordan Rivera"`, `fill email with "jordan@example.com"`, `pause
"click the Submit button"` (4B) and the equivalent for 36B (fleet), both
reaching `state: paused` with both pre-pause `field_value` checks
(`#signup-name`, `#signup-email`) passing (`ok: true`), scored
`success: true`. This is a real model-authored script correctly stopping
at a pause with the checks that matter (the fields it filled before the
pause) verified, not a scenario the harness engineered to succeed.

**Live `:1238` nav-lane call counts, from `fell_to_model` row counts per
run (one row = one live call, same accounting `harness/README.md` already
uses):** 4B baseline 4, 4B on-site 3, 36B (fleet) baseline 9,
36B (fleet) on-site 9 - **25 live nav-lane calls total across tonight's
2x2**, none of them stubbed or simulated.

## Mechanism: the shipped payload gives the model no current-page context

Phase A's shipped-payload variant (`brainstorm/shipped_payload.js`, loading
the real `buildBrainstormPayload()`) sends only `{"goal": "<text>"}` as the
user turn - no URL, no page title, no indication that a `teach`/authoring
session is already sitting on the relevant page. This is the root cause
behind Finding (a) above, and it is a genuine, reproducible property of the
shipped product's brainstorm-lane prompt, not an artifact of this bench's
goal phrasing (the design doc's own goal-phrasing convention, section 5,
deliberately mirrors real `teach` usage - a real user sitting on the same
page would get the same model behavior under the shipped payload). Two
sub-patterns of `go`-first authoring were observed (a third, described in
an earlier version of this document, turned out to be a misattributed
instance of the second - see "Correction" below):

1. A plausible-looking but invented domain (e.g. `go products.page.com`,
   `go signuptemplate.com`) - `resolveGoLadder()`'s step 1
   (`resolveLiteralDestination()`) resolves it as a literal `https://`
   hostname (it has a dot, so it looks like a domain) WITHOUT ever
   consulting the model. Approving its nav-confirm would make Chrome open a
   REAL, DIRECT (not Tor-proxied) connection to an arbitrary third party,
   which the design's own framing of the fixture tier as self-contained
   does not anticipate. **Build-time deviation from the design doc**
   (flagged in the original build report): `harness/task_runner.py` adds a
   nav-confirm origin allowlist (fixture tier: only the local corpus
   origin; realsite tier: only `https://*.wikipedia.org`) and rejects
   (Escape) anything else, bucketed `halted` with an explicit "harness
   safety policy, not a product-side halt" note in the evidence. This is
   the ONLY sub-pattern that is genuinely deterministic/product-side.
2. Anything else non-empty (a bare word like `products`, a natural-language
   phrase like `"green gizmo store"`, a quoted full URL like
   `"https://example-signup.com/form"`) - `resolveGoLadder()`'s step 1
   fails (no dot, or not literal-URL-shaped for the ladder's purposes) and
   step 2 (alias) never fires (no alias was ever defined for these
   scripts), so the ladder returns `{ok:false, needsNavLane:true}` - see
   `nav.js`'s own step-3 comment: "steps 1-2 both missed; caller must fall
   back to the nav-lane model call... with the ORIGINAL typed command
   text". At that point `terminal.js`'s `_handleGo()` makes a REAL
   `NAV_LLM_REQUEST` call to the extension's hardcoded `127.0.0.1:1238`
   endpoint (not `:1236`/`:1241`, and not stopped/started/touched by this
   build) and one of two things happens with the model's response:
   - the model proposes `{action: "navigate", value: "..."}` -> surfaces
     as a `pendingNav` card with `modelResolved: true`, always rejected
     (Escape) by `task_runner.py`, bucketed `fell_to_model` directly.
   - the model declines to navigate (`action` is something other than
     `"navigate"`, e.g. because it judged the destination too vague) ->
     `_handleGo()` prints `go: ${navAction.reason || ...}` and settles the
     run as a failed step WITHOUT ever showing a `pendingNav` card - this
     looks, from the outside, exactly like a deterministic ladder
     rejection, but a real `:1238` call already happened and the printed
     text is THE MODEL'S OWN REASON, not a fixed string. **This is the bug
     an earlier version of this document got wrong** (see "Correction"
     below).

**Correction (verify-pass fix, 2026-07-17):** an earlier version of this
document bucketed 3 rows (`shop-open-red-gadget`, `shop-open-green-gizmo`,
`shop-open-item-back-to-products`, all with a `go "products"` /
`go products` first step) as `halted` with the claim that "the product's
OWN `go`-verb literal-resolution ladder deterministically refuses" a
too-generic word. That claim is false: `resolveGoLadder({arg: "products"})`
returns `{ok:false, needsNavLane:true}` (verified directly against the real,
unmodified `nav.js` - see `harness/tasks/resolve_go.js` and its R1 check
below), which means the ladder does NOT reject `"products"` itself - it
falls through to the nav-lane model call, exactly as sub-pattern 2 above
describes. The tell that gave this away: the SAME input (`"products"`)
produced differently-worded messages across rows that hit it - a
deterministic string table cannot do that; a live model sampling a
free-text `reason` field can. By this bench's own criterion for
`fell_to_model` (a real nav-lane model call happened), all such rows are
`fell_to_model`, not `halted`.

`harness/task_runner.py` pre-classifies every `go` step's argument through
`harness/tasks/resolve_go.js` (which requires the real, unmodified `nav.js`
and calls its real `resolveGoLadder()`, never reimplemented) BEFORE each
run, and reclassifies a genuine product-side `halted` outcome (i.e. NOT the
harness's own nav-confirm-allowlist rejection, sub-pattern 1 above) to
`fell_to_model` whenever the failing step's `go` argument resolves
`needsNavLane: true`. Classification never matches on the model's message
text; it is driven entirely by the real product resolver's own verdict on
the argument.

## Stochasticity disclosure

Authoring is sampled (`temperature: 0.1`, see "The shipped payload pins
temperature 0.1" in LIMITATIONS below) - re-authoring the same goal set
against the same model can produce a different bucket mix even when the
headline number does not move. The earlier single-condition 4B baseline
run (`authored-lfl-cohort-4b-20260717T075902Z.json` ->
`tasks-run-lfl-cohort-4b-20260717T083339Z.json`, authored 07:59 UTC) scored
`halted 8 / fell_to_model 6` - a different bucket mix from tonight's
re-authored baseline cell (`halted 10 / fell_to_model 4`, same model, same
condition, same corpus). The `task_success 0/14` headline is unchanged
between the two runs; only the internal halted/fell_to_model split moved,
consistent with the same underlying go-first-step failure mode being hit by
differently-shaped invented destinations from one sampling to the next.
**Tonight's full 2x2 supersedes that single earlier run as this document's
canonical result; the 07:59 run is kept here only as a footnote showing the
bucket mix is not perfectly stable run to run, and is not otherwise cited
above.**

## Verification-plan smokes run during this build (design doc section 7, subset)

These are build-time smokes (not the full Fable verification pass), all
run for real on this dev machine 2026-07-17:

- **Hand-written known-good script** (`open "Browse products"` then
  `open "Blue Widget"`, seeded for `shop-open-blue-widget`): reached
  `completed`, both success checks passed. Proves the seed -> run ->
  multi-step watch -> completion -> checks path works end to end when a
  script does not open with a `go` preamble.
- **Hand-written wrong-plan script** (same scenario, but `open "Red
  Gadget"` as the second step): reached `completed`, checks failed
  (wrong item), correctly bucketed `wrong_plan`.
- **Seeded-bypass** (`click 3` seeded directly into
  `chrome.storage.local.lflScripts`, bypassing `setScript()`/
  `validateScriptBody()` entirely): `run` rejected it before ever showing
  the plan-preview card - `stored script "..." is invalid: step 1: "click"
  always addresses a page element by its ls-listing index - this cannot be
  safely replayed later; use pause and do it manually instead`. This is
  `parseScriptBody()`'s own run-time re-parse (called again inside
  `_handleRunCommand`), not `validateResolvedStep()` specifically (that
  function's own post-substitution/alias-expansion check is a narrower
  case this literal-body smoke does not exercise) - both are the same
  "run re-validates independently of write" property the design doc's
  ground-truth section 2 describes, and either one firing proves seeding
  cannot smuggle an index-addressed step past the product.
- **expect_pause path** (hand-written `fill name with "Jordan Rivera"`,
  `fill email with "jordan@example.com"`, `pause "click the Submit
  button"`, seeded for `signup-contact-pause`): reached `paused`, both
  pre-pause `field_value` checks passed, classified `success=true`.

Additional verification-pass evidence (2026-07-17, this dev machine, real
runs, not invented):

- **R1 - `resolve_go.js` unit-ish check**, fed straight to
  `harness/tasks/resolve_go.js` on stdin:
  - `{"arg": "products"}` -> `{"ok":false,"needsNavLane":true}` (quoted
    multiword/non-domain input correctly falls to the nav-lane).
  - `{"arg": "wikipedia.org"}` -> `{"ok":true,"url":"https://wikipedia.org/","step":"literal"}`
    (a literal domain resolves deterministically, `needsNavLane` absent).
  - `{"arg": "https://en.wikipedia.org/wiki/X"}` -> `{"ok":true,"url":"https://en.wikipedia.org/wiki/X","step":"literal"}`
    (a literal URL resolves deterministically).
- **R2 - full fixture-tier Phase B re-run**, corrected runner, same
  authored JSON the original build run consumed
  (`authored-lfl-cohort-4b-20260717T075902Z.json`):
  `task_success 0/14, halted 8, fell_to_model 6` - the run cited in
  "Stochasticity disclosure" above as the pre-canonical single-condition
  baseline (raw output in
  `tasks-run-lfl-cohort-4b-20260717T083339Z.json`).
- **R3 - degenerate-script probe on `shop-open-item-back-to-products`**:
  the hand-written 1-step script `open "Browse products"` (no `go`, no
  "open the item, then go back") reached `completed`, both end-state
  checks passed (`url_contains products.html`, `text_visible
  PRODUCTS-LIST-MARKER`) - WITHOUT `min_steps_executed` this would have
  scored `success=true`, a false positive for a goal that names a specific
  3+-step path. With the `min_steps_executed: 3` floor now on that
  scenario, `steps_executed` was `0` (see the `steps_executed` undercount
  limitation below - the single step navigated, resetting `lastResult`),
  which is `< 3`, so the row was correctly demoted to
  `success=false, bucket=wrong_plan` with an explicit
  `{"type": "min_steps_executed", "value": 3, "observed": 0, "ok": false}`
  entry appended to `checks`.

## LIMITATIONS (read this as part of the result)

- **Goals encode visible labels.** Every goal names the visible link
  text/label it expects the model to use (design doc section 5's
  convention) - this mirrors real `teach` usage but means the bench never
  tests whether a model can infer an unnamed destination.
- **The on-site condition is a goal-text manipulation only.** Prefixing
  the goal with "You are already on the correct site." changes what the
  goal SAYS, not what the product SENDS - the shipped payload passed to
  the real model still carries no URL, no page title, and no other page
  context in either condition (see "Methodology" above). A model that
  reliably honors an explicit sentence in the goal text is not the same
  thing as a model that would infer the same fact from real page context
  it was never given; this bench has not measured the latter.
- **Seeded entry path, not the `teach`-UI path.** Scripts enter storage via
  a direct service-worker eval into `chrome.storage.local.lflScripts`, not
  via `teach ... -> save`. The wire-payload equivalence is proven
  (`brainstorm/shipped_payload.js` calls the real `buildBrainstormPayload()`);
  the UI path itself is smoked manually, not benched automatically (design
  doc section 3).
- **Teach-equivalence smokes (design doc section 7.5) are still pending** -
  listed here as an open verification item, not yet run as part of this
  build or the tonight's 2x2.
- **Fixture pages are model-blind but authored by us.** No adversarial or
  organic-web noise; every marker, label, and link text was chosen to be
  unambiguous.
- **Success checks are per-goal handwritten**, same posture as
  `harness/scenarios.json`'s assertions.
- **`nav_confirms` are counted human-equivalent approvals** (Enter presses
  this harness gives on a `pendingNav` card) - a real human could of course
  decline one; this bench always approves an allowlisted nav-confirm and
  always rejects everything else (see "Mechanism" above).
- **`steps_executed` is a best-effort diagnostic** - a change-detector on
  the observed `lastResult` field, which can undercount when two
  consecutive steps both navigate quickly enough that an intermediate
  settle is never observed before the next page's freshly injected
  `Terminal()` instance resets `lastResult` to `null` (see `terminal.js`'s
  own `_lastResult = null` constructor default; the R3 degenerate-script
  probe above is itself a live example - it observed `steps_executed: 0`
  for a 1-step run that did navigate; tonight's `shop-open-signup` 4B
  on-site row, Finding (d) above, is a related timing case where the
  end-state check itself read before the navigation had settled). It is
  now used for ONE scoring purpose only - the `min_steps_executed` floor
  described below - never to distinguish `completed` from anything else;
  final run `state` and the end-state success checks are otherwise
  unaffected by this undercount.
- **N is small** (14 fixture goals, 4 realsite goals) and **single
  machine**.
- **4B on iGPU Vulkan1** vs **36B (fleet) on the fleet's B70** - latency
  numbers are not comparable across models even now that both have real
  runs; task-success rates are the number this bench is actually for.
- **The nav-confirm origin allowlist is a build-time addition**, not in
  the original design doc text (see "Mechanism" above and this build's
  final report) - it changes what a run bucket looks like (an off-allowlist
  `go` is `halted` by harness policy, not left to actually navigate) but
  does not change the product under test. The realsite-tier allowlist now
  also pins scheme (`https://*.wikipedia.org` / `https://wikipedia.org`
  only, not a bare `.wikipedia.org` suffix match) - see `nav_origin_allowed()`
  in `harness/task_runner.py`; the fixture-tier check stays local
  `http://127.0.0.1:<port>` on purpose, since the self-contained corpus
  server never speaks https.
- **Success checks are end-state-only, and path-dependent goals are
  gameable by construction.** Every `success` check runs against the FINAL
  page/DOM state, so a goal whose text implies a specific PATH (e.g.
  `shop-open-item-back-to-products`: go to products, open an item, then go
  back) can score `success` on a degenerate script that reaches the right
  end state by a shortcut the goal never asked for (a live example: a
  1-step `open "Browse products"` script lands on `products.html` directly
  and passes both of that goal's end-state checks). The optional
  per-scenario `min_steps_executed` field (`task-scenarios.json`) closes
  this for goals that need it: if `steps_executed` is below the declared
  floor, an otherwise-passing row is demoted to `wrong_plan` at scoring
  time (see `harness/README.md`'s task-success section for the field's
  contract). Set to `3` on `shop-open-item-back-to-products` (documented
  in the "R3" smoke above); no other current fixture goal needed it. This
  is a floor, not a real path-shape check - a wrong-but-long-enough script
  can still pass if its end state happens to match.
- **The shipped payload pins `temperature: 0.1`**
  (`service-worker.js:166`'s `TEMPERATURE` constant, read by
  `buildBrainstormPayload()` unmodified via `shipped_payload.js` - see that
  file's header). The design doc's own section 6 text says "temperature
  0.2"; that number was inherited from `brainstorm/probe.py`'s
  `call_model()` used by the `strict`/`naive` probe variants (its own
  hardcoded `0.2`, unrelated to the product), written before the brainstorm
  lane shipped and the `shipped` variant existed. `author_tasks.py` only
  ever uses the `shipped` variant, so every number in this document is at
  the product's real, pinned `0.1` - shipped fidelity wins over the design
  doc's stale cross-reference.
