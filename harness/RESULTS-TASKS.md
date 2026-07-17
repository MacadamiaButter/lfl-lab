# RESULTS-TASKS - task-success bench (goal -> authored script -> real execution -> observed outcome)

Design doc: `LFL-LAB-TASK-SUCCESS-BENCH-DESIGN.md` (2026-07-17, approved,
kept outside this repo with the operator's other planning docs). This is a
skeleton with the table structure the design calls for (section 6) and one
real, initial 4B fixture-tier run filled in - every other cell is TBD,
never invented. Regenerate/extend it yourself with
`harness/author_tasks.py` (Phase A) then `harness/task_runner.py`
(Phase B) - see `harness/README.md`'s task-success section for the exact
commands.

Read the LIMITATIONS section as part of the result, same posture as
`harness/RESULTS.md` and `harness/RESULTS-AB.md` - this bench's honesty is
its credibility, not a footnote to it.

## Headline result so far

**4B (`lfl-cohort-4b`, `127.0.0.1:1241`, shipped payload), fixture tier,
2026-07-17: authored_valid 14/14 (attempt 1; also 14/14 any-attempt - see
"authored_valid, precisely" below), task_success 0/14 (n_rated 14, 0
excluded as `harness_error` - see "denominator, precisely" below).** The
0/14 is not a harness failure - see "Key finding" below. It is a real,
fully-attributed measurement: every one of the 14 authored scripts opened
with a `go <destination>` step despite the run already starting on the
correct page, and every one of those destinations was either rejected by
this harness's own nav-confirm safety policy (8 rows) or required a live
nav-lane model call to `:1238` that then declined to navigate (6 rows) -
before any task-relevant step ran (see the corrected bucket table below).

**Corrected 2026-07-17 (verify-pass fix):** an earlier version of this
section misattributed 3 of those 14 rows (`shop-open-red-gadget`,
`shop-open-green-gizmo`, `shop-open-item-back-to-products`) to the
product's DETERMINISTIC `go`-verb resolution ladder. That was wrong - see
"Key finding" below for the corrected mechanism and
`harness/tasks/resolve_go.js` for the fix. The bucket counts in this
document are now taken directly from a re-run with the corrected runner
(`harness/results/tasks-run-lfl-cohort-4b-20260717T083339Z.json`), not
recomputed by hand.

**authored_valid, precisely.** Design doc section 6 defines `authored_valid`
as "a goal counts valid if attempt 1 is valid - attempt 2 is recorded for
stability info only" - `harness/author_tasks.py` now reports this exact
number (`n_valid_attempt1`) separately from the any-of-2-attempts number
(`n_valid_any_attempt`), which an earlier version of this script conflated
under one ambiguous `n_valid` field. For this run both happen to be 14/14
(every goal's first attempt was already valid), so the distinction does not
change this run's headline, but the field names in
`harness/results/authored-*.json` now say precisely which number is which.

**denominator, precisely.** Design doc section 6 also says `harness_error`
is "excluded from rates, counted" - `harness/task_runner.py` now computes
`task_success` over `n_rated` (total rows minus `harness_error` rows), not
over the full row count, and reports the excluded count separately. This
run had 0 `harness_error` rows, so the number is unaffected here, but a run
that hits a real harness bug on one goal will no longer silently shrink the
reported rate.

35B (fleet, `:1236`) and the realsite tier are **not run in this build** -
the 35B run is explicitly owner/Fable-scheduled work outside this build
(see design doc section 8 item 5 and the hard constraint against this
build touching `:1236`); the realsite tier is wired up and smoke-tested
(see `harness/README.md`) but not run for a real published number here.

## Key finding: the shipped payload gives the model no current-page context

Phase A's shipped-payload variant (`brainstorm/shipped_payload.js`, loading
the real `buildBrainstormPayload()`) sends only `{"goal": "<text>"}` as the
user turn - no URL, no page title, no indication that a `teach`/authoring
session is already sitting on the relevant page. Given every fixture goal
here, the 4B model authored a `go <destination>` step as line 1 of every
single script, even for goals with zero navigational language (e.g.
`signup-contact-pause`'s goal is "Fill in the sign-up form with the name
Jordan Rivera and the email jordan@example.com, then pause before
submitting" - no mention of "go" or "open" at all - and the model still
opened with `go signuptemplate.com`).

This is a genuine, reproducible property of the shipped product's
brainstorm-lane prompt, not an artifact of this bench's goal phrasing (the
design doc's own goal-phrasing convention, section 5, deliberately mirrors
real `teach` usage - a real user sitting on the same page would get the
same model behavior). Two sub-patterns were observed in the corrected run
(a third, described in an earlier version of this document, turned out to
be a misattributed instance of the second - see "Correction" below):

1. A plausible-looking but invented domain (e.g. `go products.go.com`,
   `go signuptemplate.com`) - `resolveGoLadder()`'s step 1
   (`resolveLiteralDestination()`) resolves it as a literal `https://`
   hostname (it has a dot, so it looks like a domain) WITHOUT ever
   consulting the model. Approving its nav-confirm would make Chrome open a
   REAL, DIRECT (not Tor-proxied) connection to an arbitrary third party,
   which the design's own framing of the fixture tier as self-contained
   does not anticipate. **Build-time deviation from the design doc**
   (flagged in the original build report): `harness/task_runner.py` adds a
   nav-confirm origin allowlist (fixture tier: only the local corpus
   origin; realsite tier: only `https://*.wikipedia.org` - see FIX 3 below)
   and rejects (Escape) anything else, bucketed `halted` with an explicit
   "harness safety policy, not a product-side halt" note in the evidence.
   This is the ONLY sub-pattern that is genuinely deterministic/product-side
   - 8 of the 14 fixture rows land here.
2. Anything else non-empty (a bare word like `products`, a natural-language
   phrase like `"green gizmo store"`, a full URL like
   `"https://example.com/updates"`) - `resolveGoLadder()`'s step 1 fails (no
   dot, or not literal-URL-shaped for the ladder's purposes) and step 2
   (alias) never fires (no alias was ever defined for these scripts), so
   the ladder returns `{ok:false, needsNavLane:true}` - see `nav.js`'s own
   step-3 comment: "steps 1-2 both missed; caller must fall back to the
   nav-lane model call... with the ORIGINAL typed command text". At that
   point `terminal.js`'s `_handleGo()` makes a REAL `NAV_LLM_REQUEST` call
   to the extension's hardcoded `127.0.0.1:1238` endpoint (not
   `:1236`/`:1241`, and not stopped/started/touched by this build) and one
   of two things happens with the model's response:
   - the model proposes `{action: "navigate", value: "..."}` -> surfaces as
     a `pendingNav` card with `modelResolved: true`, always rejected
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
produced TWO DIFFERENTLY WORDED messages across the two rows that hit it
("... no specific site or domain named; 'products' is too generic to
resolve to a single destination" vs "... no specific site named;
'products' is too generic to resolve to a single destination") - a
deterministic string table cannot do that; a live model sampling a free-text
`reason` field can. By this bench's own criterion for `fell_to_model` (a
real nav-lane model call happened), all 3 rows are `fell_to_model`, not
`halted`.

`harness/task_runner.py` now pre-classifies every `go` step's argument
through `harness/tasks/resolve_go.js` (which requires the real,
unmodified `nav.js` and calls its real `resolveGoLadder()` - never
reimplemented) BEFORE each run, and reclassifies a genuine product-side
`halted` outcome (i.e. NOT the harness's own nav-confirm-allowlist
rejection, sub-pattern 1 above) to `fell_to_model` whenever the failing
step's `go` argument resolves `needsNavLane: true` - see that file's own
header and `classify_go_steps()`/the reclassification block in
`run_one_scenario()` for the exact logic. Classification never matches on
the model's message text; it is driven entirely by the real product
resolver's own verdict on the argument.

**Disclosed plainly:** Phase B triggered approximately 6 live `:1238`
nav-lane model calls in this fixture-tier run (the 6 rows now bucketed
`fell_to_model`) - the runner's Escape policy always rejects a
`modelResolved: true` `pendingNav` card (covering the "model proposed a
navigate" half of sub-pattern 2), and the fixed allowlist covers
nav-confirms for literal (non-model) destinations (sub-pattern 1) - but a
nav-lane abort that happens model-side, before any card is ever shown, is
neither of those; it is caught only by the pre-classification described
above. This is the mechanism the correction fixes.

None of the 14 fixture scripts got past this preamble to exercise the
actual open/search/fill/scroll/pause steps that follow it - so this run
says nothing yet about the 4B model's DOWNSTREAM plan quality on this
corpus, only about the go-preamble failure mode. That is itself a real,
useful, and slightly unflattering finding about the shipped payload as it
exists today, and it is reported as observed, not smoothed over. S2/S3/S5
(see `harness/README.md`) used hand-written scripts specifically to prove
the rest of the pipeline (seeding, multi-step watch, pause detection,
success checks, seeded-bypass rejection) works correctly once a script
gets past this preamble.

## Task-success table (design doc section 6)

`authored_valid` is reported as attempt-1 (the design's own headline
metric) / any-attempt (see "authored_valid, precisely" above) - identical
for this run. `task_success` is `n_success/n_rated` (`harness_error` rows
excluded from the denominator per design section 6 - see "denominator,
precisely" above); this run had 0.

| model | tier | authored_valid (attempt1/any) | task_success | wrong_plan | halted | fell_to_model | pause_unexpected | timeout | harness_error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 4B (`lfl-cohort-4b`, `:1241`) | fixture | 14/14 / 14/14 | 0/14 | 0 | 8 | 6 | 0 | 0 | 0 |
| 4B (`lfl-cohort-4b`, `:1241`) | realsite | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 35B (fleet, `:1236`) | fixture | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 35B (fleet, `:1236`) | realsite | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

Raw run: `harness/results/tasks-run-lfl-cohort-4b-20260717T083339Z.json`
(gitignored, not committed - regenerate with the commands in
`harness/README.md`; authored from the same
`authored-lfl-cohort-4b-20260717T075902Z.json` the original build run
consumed, re-run through the corrected runner - see "Correction" above).
Per-row detail for the 4B fixture run (bucket/evidence taken verbatim from
that raw JSON, never invented):

| goal id | bucket | evidence (trimmed) |
| --- | --- | --- |
| shop-open-blue-widget | halted | harness safety policy blocked `go products.go.com` (off-allowlist) |
| shop-open-red-gadget | fell_to_model | nav-lane model call occurred (`go "products"` needsNavLane); model's own abort reason: "no specific site or domain named; 'products' is too generic to resolve to a single destination" |
| shop-open-green-gizmo | fell_to_model | nav-lane model call occurred (`go "products"` needsNavLane); model's own abort reason: "no specific site named; 'products' is too generic to resolve to a single destination" |
| shop-open-yellow-widget | halted | harness safety policy blocked `go products.page.com` (off-allowlist) |
| shop-search-open-blue | halted | harness safety policy blocked `go product.com` (off-allowlist) |
| shop-search-open-red | halted | harness safety policy blocked `go product.com` (off-allowlist) |
| shop-search-open-green | halted | harness safety policy blocked `go product.com` (off-allowlist) |
| shop-search-third-pause | halted | harness safety policy blocked `go product.com` (off-allowlist) |
| signup-contact-pause | halted | harness safety policy blocked `go signuptemplate.com` (off-allowlist) |
| signup-newsletter-pause | halted | harness safety policy blocked `go signuptemplate.com` (off-allowlist) |
| signup-message-pause | fell_to_model | `go "https://example-signup.com/form"` - model proposed a `navigate` action, rejected (Escape) per policy |
| shop-scroll-item | fell_to_model | `go "green gizmo store"` - model proposed a `navigate` action, rejected (Escape) per policy |
| shop-open-item-back-to-products | fell_to_model | nav-lane model call occurred (`go products` needsNavLane); model's own abort reason: "no specific site named - 'products' is too generic to resolve to a single destination" |
| shop-open-signup | fell_to_model | `go "https://example.com/updates"` - model proposed a `navigate` action, rejected (Escape) per policy |

Note the three "too generic" rows above have THREE DIFFERENTLY WORDED
abort reasons for what is, in two cases, the exact same script text
(`go "products"`) - direct, in-this-run evidence that these messages are
sampled model output, not a fixed string table (this run's `:1238` answered
with the fleet's 35B model at call time, per this repo's own
model-swap-agnostic design - see `harness/README.md`'s "Model-swap A/B
workflow"; the mechanism is identical regardless of which model sits behind
that port).

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
  `task_success 0/14, halted 8, fell_to_model 6` - matches the corrected
  bucket table above exactly (see that table's per-row detail; raw output
  in `tasks-run-lfl-cohort-4b-20260717T083339Z.json`).
- **R3 - degenerate-script probe on `shop-open-item-back-to-products`**:
  the hand-written 1-step script `open "Browse products"` (no `go`, no
  "open the item, then go back") reached `completed`, both end-state
  checks passed (`url_contains products.html`, `text_visible
  PRODUCTS-LIST-MARKER`) - WITHOUT `min_steps_executed` this would have
  scored `success=true`, a false positive for a goal that names a specific
  3+-step path. With the `min_steps_executed: 3` floor now on that
  scenario, `steps_executed` was `0` (see the `steps_executed` undercount
  limitation above - the single step navigated, resetting `lastResult`),
  which is `< 3`, so the row was correctly demoted to
  `success=false, bucket=wrong_plan` with an explicit
  `{"type": "min_steps_executed", "value": 3, "observed": 0, "ok": false}`
  entry appended to `checks`.

## LIMITATIONS (read this as part of the result)

- **Goals encode visible labels.** Every goal names the visible link
  text/label it expects the model to use (design doc section 5's
  convention) - this mirrors real `teach` usage but means the bench never
  tests whether a model can infer an unnamed destination.
- **Seeded entry path, not the `teach`-UI path.** Scripts enter storage via
  a direct service-worker eval into `chrome.storage.local.lflScripts`, not
  via `teach ... -> save`. The wire-payload equivalence is proven
  (`brainstorm/shipped_payload.js` calls the real `buildBrainstormPayload()`);
  the UI path itself is smoked manually, not benched automatically (design
  doc section 3).
- **Fixture pages are model-blind but authored by us.** No adversarial or
  organic-web noise; every marker, label, and link text was chosen to be
  unambiguous.
- **Success checks are per-goal handwritten**, same posture as
  `harness/scenarios.json`'s assertions.
- **`nav_confirms` are counted human-equivalent approvals** (Enter presses
  this harness gives on a `pendingNav` card) - a real human could of course
  decline one; this bench always approves an allowlisted nav-confirm and
  always rejects everything else (see "Key finding" above).
- **`steps_executed` is a best-effort diagnostic** - a change-detector on
  the observed `lastResult` field, which can undercount when two
  consecutive steps both navigate quickly enough that an intermediate
  settle is never observed before the next page's freshly injected
  `Terminal()` instance resets `lastResult` to `null` (see `terminal.js`'s
  own `_lastResult = null` constructor default; the R3 degenerate-script
  probe below is itself a live example - it observed `steps_executed: 0`
  for a 1-step run that did navigate). It is now used for ONE scoring
  purpose only - the `min_steps_executed` floor described below - never to
  distinguish `completed` from anything else; final run `state` and the
  end-state success checks are otherwise unaffected by this undercount.
- **N is small** (14 fixture goals, 4 realsite goals) and **single
  machine**.
- **4B on iGPU Vulkan1** vs the 35B's eventual run **on the fleet's B70** -
  latency numbers will not be comparable across models even once both are
  run; task-success rates are the number this bench is actually for.
- **The nav-confirm origin allowlist is a build-time addition**, not in
  the original design doc text (see "Key finding" above and this build's
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
  in the "R3" smoke below); no other current fixture goal needed it. This
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
