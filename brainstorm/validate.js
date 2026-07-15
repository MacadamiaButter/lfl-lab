#!/usr/bin/env node
/**
 * validate.js - shells out to the REAL lfl-terminal script validator so a
 * brainstorm-lane proposal is checked by the exact same code a hand-typed
 * `script new` body goes through - zero reimplementation in this repo, zero
 * chance of this probe's notion of "valid" drifting from the product's.
 *
 * Reads one JSON object from stdin: {"body": "<raw proposed script text>"}.
 * Requires lfl-terminal's own extension/content/registry.js (read-only;
 * this repo never vendors or copies it) and calls its exported
 * parseScriptBody(body, {maxSteps: SCRIPT_MAX_STEPS}) unmodified. Prints
 * exactly what that function returns, as one line of JSON, to stdout:
 *   {"ok": true, "steps": [...], "arity": N, "usesRest": bool, "stepCount": N}
 *   {"ok": false, "reason": "..."}
 *
 * LFL_TERMINAL_EXTENSION_DIR overrides where the sibling lfl-terminal
 * checkout's extension/ dir lives; defaults to the sibling-checkout layout
 * this repo's own harness/README.md already documents
 * (~/projects/lfl-terminal/extension next to ~/projects/lfl-lab).
 */

'use strict';

const path = require('path');

const extensionDir = process.env.LFL_TERMINAL_EXTENSION_DIR
  || path.join(__dirname, '..', '..', 'lfl-terminal', 'extension');
const registryPath = path.join(extensionDir, 'content', 'registry.js');

let registry;
try {
  // eslint-disable-next-line import/no-dynamic-require, global-require
  registry = require(registryPath);
} catch (err) {
  process.stderr.write(
    `validate.js: could not load registry.js from ${registryPath}\n` +
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
    process.stderr.write(`validate.js: invalid JSON on stdin: ${err.message}\n`);
    process.exit(2);
    return;
  }
  const body = typeof input.body === 'string' ? input.body : '';
  const result = registry.parseScriptBody(body, { maxSteps: registry.SCRIPT_MAX_STEPS });
  process.stdout.write(JSON.stringify(result) + '\n');
});
