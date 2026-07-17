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
2026-07-17: authored_valid 14/14, task_success 0/14.** The 0/14 is not a
harness failure - see "Key finding" below. It is a real, fully-attributed
measurement: every one of the 14 authored scripts opened with a `go
<destination>` step despite the run already starting on the correct page,
and every one of those destinations was rejected before any task-relevant
step ran (see the bucket table).

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
same model behavior). Three sub-patterns were observed in the one real run
so far:

1. A too-generic single word (e.g. `go "products"`) - the product's OWN
   `go`-verb literal-resolution ladder deterministically refuses it
   ("... is too generic to resolve to a single destination") before any
   navigation is attempted. Bucketed `halted`, product-side, not a harness
   intervention.
2. A plausible-looking but invented domain (e.g. `go products.go.com`,
   `go signuptemplate.com`) - a real, resolvable-or-not hostname. Approving
   its nav-confirm would make Chrome open a REAL, DIRECT (not Tor-proxied)
   connection to an arbitrary third party, which the design's own framing
   of the fixture tier as self-contained does not anticipate. **Build-time
   deviation from the design doc** (flagged in the final build report):
   `harness/task_runner.py` adds a nav-confirm origin allowlist (fixture
   tier: only the local corpus origin; realsite tier: only `*.wikipedia.org`)
   and rejects (Escape) anything else, bucketed `halted` with an explicit
   "harness safety policy, not a product-side halt" note in the evidence.
3. A natural-language phrase (e.g. `go "green gizmo store"`) - fails the
   literal ladder and falls through to the extension's own nav-lane MODEL
   FALLBACK, a real call to its hardcoded `127.0.0.1:1238` endpoint (not
   `:1236`/`:1241`, and not stopped/started/touched by this build). This
   still surfaces as a `pendingNav` card with `modelResolved: true`, not as
   a `pendingProposal` - `task_runner.py` treats it the same as a model
   proposal per design section 9 sign-off E (Phase B must stay
   execution-model-independent), bucketed `fell_to_model`.

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

| model | tier | authored_valid | task_success | wrong_plan | halted | fell_to_model | pause_unexpected | timeout | harness_error |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 4B (`lfl-cohort-4b`, `:1241`) | fixture | 14/14 | 0/14 | 0 | 11 | 3 | 0 | 0 | 0 |
| 4B (`lfl-cohort-4b`, `:1241`) | realsite | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 35B (fleet, `:1236`) | fixture | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| 35B (fleet, `:1236`) | realsite | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

Raw run: `harness/results/tasks-run-lfl-cohort-4b-20260717T080447Z.json`
(gitignored, not committed - regenerate with the commands in
`harness/README.md`). Per-row detail for the 4B fixture run:

| goal id | bucket | evidence (trimmed) |
| --- | --- | --- |
| shop-open-blue-widget | halted | harness safety policy blocked `go products.go.com` (off-allowlist) |
| shop-open-red-gadget | halted | product rejected `go "products"` - "too generic to resolve to a single destination" |
| shop-open-green-gizmo | halted | product rejected `go "products"` - "too generic to resolve to a single destination" |
| shop-open-yellow-widget | halted | harness safety policy blocked `go products.page.com` (off-allowlist) |
| shop-search-open-blue | halted | harness safety policy blocked `go product.com` (off-allowlist) |
| shop-search-open-red | halted | harness safety policy blocked `go product.com` (off-allowlist) |
| shop-search-open-green | halted | harness safety policy blocked `go product.com` (off-allowlist) |
| shop-search-third-pause | halted | harness safety policy blocked `go product.com` (off-allowlist) |
| signup-contact-pause | halted | harness safety policy blocked `go signuptemplate.com` (off-allowlist) |
| signup-newsletter-pause | halted | harness safety policy blocked `go signuptemplate.com` (off-allowlist) |
| signup-message-pause | fell_to_model | `go "https://example-signup.com/form"` required nav-lane model resolution |
| shop-scroll-item | fell_to_model | `go "green gizmo store"` required nav-lane model resolution |
| shop-open-item-back-to-products | halted | product rejected the `go` step - "no specific site or domain named" |
| shop-open-signup | fell_to_model | `go "https://example.com/updates"` required nav-lane model resolution |

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
- **`steps_executed` is a best-effort diagnostic**, not used for scoring: a
  change-detector on the observed `lastResult` field, which can undercount
  when two consecutive steps both navigate quickly enough that an
  intermediate settle is never observed before the next page's freshly
  injected `Terminal()` instance resets `lastResult` to `null` (see
  `terminal.js`'s own `_lastResult = null` constructor default). Final run
  `state` and the success checks are unaffected by this.
- **N is small** (14 fixture goals, 4 realsite goals) and **single
  machine**.
- **4B on iGPU Vulkan1** vs the 35B's eventual run **on the fleet's B70** -
  latency numbers will not be comparable across models even once both are
  run; task-success rates are the number this bench is actually for.
- **The nav-confirm origin allowlist is a build-time addition**, not in
  the original design doc text (see "Key finding" above and this build's
  final report) - it changes what a run bucket looks like (an off-allowlist
  `go` is `halted` by harness policy, not left to actually navigate) but
  does not change the product under test.
