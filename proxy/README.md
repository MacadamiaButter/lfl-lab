# lfl-proxy

A tiny loopback reverse-proxy for pointing [lfl-terminal](https://github.com/MacadamiaButter/lfl-terminal)
at any local or self-hosted OpenAI-compatible model endpoint, without giving the
extension a credential or a non-loopback host permission.

## Why

The lfl-terminal extension is loopback-only by design: its single host
permission is `127.0.0.1`, and it never holds an API key. That is a security
property. This proxy lets you keep that property while pointing the extension at
a model that lives somewhere other than plain `127.0.0.1:1238`:

- a bigger model running on another local port,
- a model on a host on your own private network,
- a self-hosted endpoint that requires a key.

The proxy listens on loopback only and forwards to one upstream you configure,
injecting the key on the way out. The key stays on your machine, in an
environment variable, never in a tracked file and never sent to the extension.

The honest promise this changes: with a direct local model, nothing leaves your
device. Pointed at a remote upstream, the promise becomes "nothing leaves the
endpoint you configured." Decide that is what you want before you point it
off-box.

## What it is not

Not an open/forward proxy. It forwards to exactly one configured upstream and
refuses absolute-URI request lines, so it cannot be turned into a general relay.
It is dev infrastructure - small enough to read top to bottom, which is the
point.

## Use

```
cd proxy
cp .env.example .env.local          # fill in your upstream + key
set -a; . ./.env.local; set +a
python3 lfl-proxy.py
```

Then point lfl-terminal at `http://127.0.0.1:<LFL_PROXY_PORT>`. If you run it on
`1238` (the extension default), stop any model already bound there first.

Requires only Python 3 - no third-party packages.

## Configuration

| Variable | Required | Meaning |
| --- | --- | --- |
| `LFL_PROXY_UPSTREAM` | yes | Base URL of the upstream, e.g. `http://127.0.0.1:1236` |
| `LFL_PROXY_API_KEY` | no | Bearer token injected as `Authorization`; blank for a keyless local model |
| `LFL_PROXY_PORT` | no | Loopback port to listen on (default `1238`) |

`.env.local` is gitignored. The repo's leak gate (`tests/check_no_leaks.sh`)
fails the build if a real host or key lands in a tracked file.
