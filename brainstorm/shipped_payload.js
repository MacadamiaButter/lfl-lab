#!/usr/bin/env node
/**
 * shipped_payload.js - builds a brainstorm-lane request payload by calling
 * the REAL buildBrainstormPayload() from lfl-terminal's own, unmodified
 * background/service-worker.js - the same zero-reimplementation rule
 * validate.js applies to parseScriptBody() (see that file's header).
 *
 * Why this exists (the drift problem it kills): the probe originally kept
 * its OWN copy of the system prompt, and the product ported that copy back
 * verbatim - which left two copies that could silently drift apart, at
 * which point the probe's published numbers stop being evidence about what
 * the product actually ships. This shim ends that: the probe's "shipped"
 * variant gets its ENTIRE payload - system prompt, user-message wire format
 * (JSON.stringify({goal})), response_format json_schema, max_tokens,
 * temperature - from the product source at run time. If the product
 * changes any of it, the next probe run measures the change automatically.
 *
 * Usage: node shipped_payload.js "<goal text>"
 * Prints the payload as one JSON document on stdout. Exit 2 with a stderr
 * hint if the product checkout cannot be found.
 *
 * LFL_TERMINAL_EXTENSION_DIR overrides where lfl-terminal's extension/ dir
 * lives (same env var validate.js already honors); defaults to the sibling
 * checkout layout (~/projects/lfl-terminal next to ~/projects/lfl-lab).
 *
 * The service worker is loaded in a Node `vm` sandbox with inert stand-ins
 * for the chrome.* APIs it registers against at load time (message/tab
 * listeners, session storage) - the same technique lfl-terminal's own
 * tests/brainstorm_lane_isolation.test.js uses. Nothing here ever calls
 * fetch: only the pure payload-builder function is invoked.
 */

'use strict';

const vm = require('vm');
const fs = require('fs');
const path = require('path');

const extensionDir = process.env.LFL_TERMINAL_EXTENSION_DIR
  || path.join(__dirname, '..', '..', 'lfl-terminal', 'extension');
const swPath = path.join(extensionDir, 'background', 'service-worker.js');

const goal = process.argv[2];
if (typeof goal !== 'string' || !goal.trim()) {
  process.stderr.write('usage: node shipped_payload.js "<goal text>"\n');
  process.exit(2);
}

let swSrc;
try {
  swSrc = fs.readFileSync(swPath, 'utf8');
} catch (err) {
  process.stderr.write(
    `shipped_payload.js: could not read service-worker.js from ${swPath}\n` +
    '(set LFL_TERMINAL_EXTENSION_DIR if your lfl-terminal checkout lives elsewhere)\n' +
    `${err && err.message}\n`
  );
  process.exit(2);
}

// Inert chrome/global stand-ins: enough for service-worker.js to LOAD (it
// registers listeners and reads nothing at top level beyond these), never
// enough for it to DO anything - no network, no timers that fire.
const sandbox = {};
sandbox.self = sandbox;
sandbox.globalThis = sandbox;
sandbox.importScripts = () => {}; // ratelimit.js is only needed by handlers this shim never invokes
sandbox.setTimeout = () => 0;
sandbox.clearTimeout = () => {};
sandbox.fetch = () => { throw new Error('shipped_payload.js must never reach fetch'); };
sandbox.AbortController = function AbortController() { this.signal = {}; this.abort = () => {}; };
sandbox.chrome = {
  runtime: { onMessage: { addListener() {} } },
  storage: {
    session: {
      get: () => Promise.resolve({}),
      set: () => Promise.resolve(),
      remove: () => Promise.resolve(),
    },
  },
  tabs: { onRemoved: { addListener() {} } },
};
vm.createContext(sandbox);
vm.runInContext(swSrc, sandbox, { filename: 'service-worker.js' });

if (typeof sandbox.buildBrainstormPayload !== 'function') {
  process.stderr.write(
    'shipped_payload.js: buildBrainstormPayload() not found in the loaded ' +
    'service-worker.js - has the product renamed it? Update this shim to match.\n'
  );
  process.exit(2);
}

sandbox.__probeGoal = goal;
const payload = vm.runInContext('buildBrainstormPayload({ goal: __probeGoal })', sandbox);
process.stdout.write(JSON.stringify(payload));
