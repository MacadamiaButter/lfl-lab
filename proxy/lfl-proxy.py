#!/usr/bin/env python3
"""lfl-proxy - a tiny loopback reverse-proxy for pointing lfl-terminal at any
local (or self-hosted) OpenAI-compatible model endpoint.

WHY THIS EXISTS
---------------
The lfl-terminal browser extension is deliberately loopback-only: its single
host permission is 127.0.0.1, and it never holds a credential. That is a
security property, not a limitation to work around. But you may want to point
it at a model that lives somewhere else - a bigger model on another port, a
host on your own private network, or a self-hosted endpoint that requires an
API key.

This proxy is the clean bridge. It listens on 127.0.0.1 only, and forwards
every request to ONE upstream you configure, injecting the API key on the way
out. The key stays here, on your machine, in an environment variable - it is
never sent to the extension and never lives in a tracked file. The extension
keeps talking to plain loopback and never learns the upstream address or key.

The honest promise this changes: with a direct local model, nothing leaves your
device. With this proxy pointed at a remote upstream, the promise becomes
"nothing leaves the endpoint you configured." State that plainly to yourself
before you point it off-box.

WHAT IT IS NOT
--------------
Not an open/forward proxy. It forwards to exactly one configured upstream and
ignores absolute-URI / CONNECT requests, so it cannot be turned into a general
relay. It is dev infrastructure - small enough to read in full, which is the
point.

CONFIG (environment variables; see .env.example)
------------------------------------------------
  LFL_PROXY_UPSTREAM   required. Base URL of the upstream, e.g. http://HOST:PORT
  LFL_PROXY_API_KEY    optional. Bearer token injected as Authorization.
  LFL_PROXY_PORT       optional. Loopback port to listen on (default 1238).

RUN
---
  export LFL_PROXY_UPSTREAM=http://your-model-host:port
  export LFL_PROXY_API_KEY=...            # if the upstream needs one
  python3 lfl-proxy.py
"""

import os
import sys
import http.server
import urllib.request
import urllib.error

# Loopback ONLY. This is the security property the whole design rests on: the
# extension talks to 127.0.0.1 and nothing else. Do not make this
# configurable to 0.0.0.0 - binding a key-injecting proxy to a routable
# interface would hand anyone on the network an authenticated relay to your
# upstream.
LISTEN_HOST = "127.0.0.1"

DEFAULT_PORT = 1238
FORWARD_TIMEOUT_S = 300

# Hop-by-hop headers we never copy from the incoming request to the upstream
# (and any inbound Authorization is dropped too - we inject our own below, so
# the extension can never override the key we hold).
_STRIP_REQUEST_HEADERS = {"host", "authorization", "connection", "content-length"}


def _env_or_die():
    upstream = os.environ.get("LFL_PROXY_UPSTREAM", "").strip().rstrip("/")
    if not upstream:
        sys.stderr.write(
            "ERROR: LFL_PROXY_UPSTREAM is not set.\n"
            "       Set it to the base URL of your model endpoint, e.g.:\n"
            "         export LFL_PROXY_UPSTREAM=http://your-model-host:port\n"
            "       (or put it in a gitignored proxy/.env.local and source that)\n"
        )
        raise SystemExit(1)
    if not (upstream.startswith("http://") or upstream.startswith("https://")):
        sys.stderr.write("ERROR: LFL_PROXY_UPSTREAM must start with http:// or https://\n")
        raise SystemExit(1)
    api_key = os.environ.get("LFL_PROXY_API_KEY", "").strip()
    try:
        port = int(os.environ.get("LFL_PROXY_PORT", str(DEFAULT_PORT)))
    except ValueError:
        sys.stderr.write("ERROR: LFL_PROXY_PORT must be an integer\n")
        raise SystemExit(1)
    return upstream, api_key, port


UPSTREAM, API_KEY, PORT = _env_or_die()

# Connect DIRECTLY to the configured upstream, ignoring any ambient
# HTTP_PROXY / HTTPS_PROXY in the environment. The upstream is a local or
# private-network model endpoint; routing it through a system/corporate/Tor
# proxy (which urllib would otherwise do by default) breaks a loopback or
# private-address upstream. An empty ProxyHandler disables that behavior.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    # Quieter default logging: method + path + status only, NEVER the body or
    # the Authorization header (which would print the key).
    def log_message(self, format, *args):  # noqa: A002 - name matches the base signature
        sys.stderr.write("lfl-proxy %s\n" % (format % args))

    def _forward(self):
        # Only ever forward to the single configured upstream. An absolute-URI
        # request line (open-proxy style) is refused outright.
        if self.path.startswith("http://") or self.path.startswith("https://"):
            self.send_error(403, "this proxy forwards only to its configured upstream")
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length > 0 else None

        headers = {}
        for key, value in self.headers.items():
            if key.lower() in _STRIP_REQUEST_HEADERS:
                continue
            headers[key] = value
        if API_KEY:
            headers["Authorization"] = "Bearer " + API_KEY

        url = UPSTREAM + self.path
        req = urllib.request.Request(url, data=body, headers=headers, method=self.command)

        try:
            with _OPENER.open(req, timeout=FORWARD_TIMEOUT_S) as resp:
                self.send_response(resp.status)
                for key, value in resp.headers.items():
                    if key.lower() in ("transfer-encoding", "connection"):
                        continue
                    self.send_header(key, value)
                self.end_headers()
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except urllib.error.HTTPError as exc:
            # Pass a real upstream error status/body straight through - useful
            # for debugging a misconfigured model, and it never contains our key.
            self.send_response(exc.code)
            self.end_headers()
            self.wfile.write(exc.read())
        except Exception as exc:  # noqa: BLE001 - report any transport failure cleanly
            self.send_error(502, "upstream unreachable: %s" % exc.__class__.__name__)

    # http.server dispatches by method name; wire the ones a model API uses.
    do_GET = _forward
    do_POST = _forward
    do_OPTIONS = _forward


def main():
    server = http.server.ThreadingHTTPServer((LISTEN_HOST, PORT), ProxyHandler)
    key_note = "with key injection" if API_KEY else "no key (none configured)"
    sys.stderr.write(
        "lfl-proxy listening on http://%s:%d -> %s (%s)\n"
        % (LISTEN_HOST, PORT, UPSTREAM, key_note)
    )
    sys.stderr.write("point lfl-terminal at http://%s:%d and stop with Ctrl+C\n" % (LISTEN_HOST, PORT))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\nlfl-proxy stopped\n")
        server.server_close()


if __name__ == "__main__":
    main()
