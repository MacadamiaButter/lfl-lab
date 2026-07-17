#!/usr/bin/env node
/**
 * resolve_go.js - shells out to the REAL lfl-terminal `go`-verb resolution
 * ladder so harness/task_runner.py can pre-classify a script's `go <arg>`
 * steps by the exact same code path terminal.js's _handleGo() uses - zero
 * reimplementation, zero chance of this repo's notion of "does this arg need
 * the nav-lane model" drifting from the product's, same rule
 * validate.js/shipped_payload.js already apply (see those files' headers).
 *
 * Why this exists (the misattribution it fixes): a Fable verify pass found
 * that harness/RESULTS-TASKS.md had misattributed 3 fixture-tier task rows
 * to the product's DETERMINISTIC go-ladder ("too generic to resolve to a
 * single destination" / "no specific site named") when those messages were
 * actually authored by the LIVE nav-lane model on :1238 - resolveGoLadder()
 * returns {ok:false, needsNavLane:true} for any non-empty, non-literal arg
 * (see nav.js's own step-3 comment), at which point terminal.js's _handleGo()
 * makes a real NAV_LLM_REQUEST call and prints back WHATEVER REASON the
 * model gave for declining to navigate - which is why the SAME input
 * ("products") produced two DIFFERENTLY WORDED messages across two rows in
 * the one real run this bench has: the messages are model output, not a
 * deterministic string table. See RESULTS-TASKS.md's corrected sub-pattern
 * section for the full writeup.
 *
 * nav.js is dual-mode CommonJS/browser-global, exactly like registry.js
 * (module.exports under Node, window.LFL.nav in the browser) and its
 * resolution logic makes zero chrome.* calls and touches no DOM - so, unlike
 * shipped_payload.js's vm-sandboxed load of service-worker.js, this file can
 * require() it directly, the same way validate.js requires registry.js.
 *
 * Reads one JSON object from stdin: {"arg": "<go step argument>"}. Prints
 * exactly what resolveGoLadder() returns, as one line of JSON, to stdout:
 *   {"ok": true, "url": "https://...", "step": "literal"|"alias"}
 *   {"ok": false, "needsNavLane": true}
 *   {"ok": false, "reason": "..."}
 *
 * No aliasLookup is wired up (this shim always passes a function that
 * returns null) - task_runner.py never runs an `alias ...` command before
 * seeding/running a fixture script, so step 2 of the real ladder (alias
 * expansion) can never fire for anything this bench executes; passing a
 * null lookup here is the honest match for that, not an approximation of
 * the ladder itself (which is loaded and called unmodified).
 *
 * LFL_TERMINAL_EXTENSION_DIR overrides where the sibling lfl-terminal
 * checkout's extension/ dir lives; defaults to the sibling-checkout layout
 * this repo's own harness/README.md already documents
 * (~/projects/lfl-terminal/extension next to ~/projects/lfl-lab).
 */

'use strict';

const path = require('path');

const extensionDir = process.env.LFL_TERMINAL_EXTENSION_DIR
  || path.join(__dirname, '..', '..', '..', 'lfl-terminal', 'extension');
const navPath = path.join(extensionDir, 'content', 'nav.js');

let nav;
try {
  // eslint-disable-next-line import/no-dynamic-require, global-require
  nav = require(navPath);
} catch (err) {
  process.stderr.write(
    `resolve_go.js: could not load nav.js from ${navPath}\n` +
    `(set LFL_TERMINAL_EXTENSION_DIR if your checkout lives elsewhere)\n` +
    `${err && err.message}\n`
  );
  process.exit(2);
}

let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => { raw += chunk; });
process.stdin.on('end', () => {
  let input;
  try {
    input = JSON.parse(raw);
  } catch (err) {
    process.stderr.write(`resolve_go.js: invalid JSON on stdin: ${err.message}\n`);
    process.exit(2);
    return;
  }
  const arg = typeof input.arg === 'string' ? input.arg : '';
  const result = nav.resolveGoLadder({ arg, aliasLookup: () => null });
  // JSON.stringify drops a URL object's own toJSON()-free internals cleanly
  // (URL implements toJSON -> the href string), so {ok:true, url, step}
  // serializes as {"ok":true,"url":"https://...","step":"literal"}.
  process.stdout.write(JSON.stringify(result) + '\n');
});
