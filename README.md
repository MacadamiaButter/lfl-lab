# lfl-lab

An open research bench for [lfl-terminal](https://github.com/MacadamiaButter/lfl-terminal):
swap local models behind a fixed, human-approved action set, and stress-test the
trust boundary with adversarial pages.

> Early and in the open. This is a lab, not a product. Expect rough edges, and
> expect the experiments here to feed back into lfl-terminal's design rather
> than ship as-is.

## What this is

lfl-terminal drives a web page from a command-line overlay: a local model
proposes one action from a fixed set of primitives, and a human approves before
anything touches the page. lfl-lab is where the harder questions about that
design get tested out loud:

- Does the approval gate still hold when you swap the small default model for a
  much larger one? For a different model family entirely?
- How does a hostile page try to break the gate, and does it?
- Can a bigger model help you *author* new terminal commands, without ever
  widening what the model is allowed to execute?

The goal is to answer those with runnable experiments and published numbers, not
assertions.

## The one line everything here follows

**No model reachable by untrusted page content may hold, or retrieve, private
data. What a model is allowed to hold is decided by the trust of its input, not
by which model it is. And the set of actions a model can emit is fixed - it can
never grow that set itself; only a human, approving a composition of the
existing actions, grows what the terminal can do.**

Every experiment in this repo is built to respect that line, and several are
built specifically to try to violate it and show that it holds.

## What is here now

- **`proxy/`** - a tiny loopback reverse-proxy so you can point the loopback-only
  extension at a model on another port or host, with the API key held on your
  machine and never handed to the extension. Zero dependencies, small enough to
  read in full. See [`proxy/README.md`](proxy/README.md).
- **`harness/`** - a Playwright rig that drives the real, unpacked lfl-terminal
  extension against a small corpus of benign and adversarial local pages, and
  logs every model proposal, human-gate verdict, and outcome. Includes the
  first adversarial battery: prompt injection, an approval-gate occlusion
  attempt, and cross-origin redirect bait, all run with the runner approving
  the proposed action so the question is whether the guard beneath the model
  holds, not whether the model behaves. See [`harness/README.md`](harness/README.md)
  for how to run it and what each scenario proves.
- **`brainstorm/`** - the brainstorm-lane probe: can a much larger model
  reliably *author* valid, safe lfl-terminal scripts (never drive a browser,
  just propose a script body) given a plain-English goal? Every proposal is
  checked by the real, unmodified `parseScriptBody()` from a sibling
  lfl-terminal checkout, reached by shelling out to `node` - never
  reimplemented here. See
  [`brainstorm/BRAINSTORM-PROBE.md`](brainstorm/BRAINSTORM-PROBE.md) for the
  headline numbers, the failure-mode breakdown, and the honest limitations.
- **`tests/check_no_leaks.sh`** and **`tests/check_no_emdash.sh`** - the
  pre-publish hygiene gates every commit in this repo passes before it is
  pushed.

## Roadmap

- **Wider adversarial corpus and model-swap A/B** - more pages that try to
  defeat the approval gate, run against several model backends behind one
  interface, with published comparisons on wrong-action rate and injection
  resistance across models (today's model-swap workflow is manual - see
  `harness/README.md`).
- **Brainstorm lane in the product** - `brainstorm/` answers whether a large
  model CAN author valid scripts; wiring that into lfl-terminal itself as a
  trusted design conversation (goal in, `parseScriptBody()`-validated
  proposal out, human approves before `setScript()` ever runs) is a separate,
  not-yet-started build.

## Relationship to lfl-terminal

lfl-terminal is the product: lean, packaged, and conservative. lfl-lab is the
research it draws on. Things prove out here first; only what earns its place, and
survives the adversarial pass, makes it into the extension.

## License

Apache-2.0. See [LICENSE](LICENSE).
