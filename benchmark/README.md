# benchmark/ - capacity load test

A small, dependency-free load harness that answers one question for the
hosted-gateway design: **how many concurrent users can one local model endpoint
on this box actually serve, and how does latency degrade as that number rises?**

It fires brainstorm-style chat-completion requests (the same request *shape* the
lfl-terminal lanes make) at an OpenAI-compatible endpoint under a sweep of
concurrency levels, and records throughput (req/s and tok/s), latency
percentiles (p50/p95/p99), and the error rate at each level.

## What it measures, honestly

The result is a **degradation curve**: throughput and latency as a function of
the number of concurrent in-flight clients. Read `RESULTS-LOAD.md` for the
committed numbers and the honest framing; the short version:

- The **35B** (`:1236`) is started with `--parallel 1` - a single decode slot -
  so concurrent requests genuinely serialize: throughput is flat and latency
  grows roughly linearly with concurrency. That is the honest "serialized
  service under load" number, not parallel throughput.
- The **4B** (`:1238`) is started with **no** explicit `--parallel` flag (server
  default), and empirically it *does* extract throughput gains from a few
  concurrent requests before saturating. The harness measures that directly
  rather than assuming a slot count.

This is not a benchmark of a multi-slot, continuously-batched production
deployment (that would be a different `--parallel` setting and a different
test). It measures the endpoints as the fleet actually runs them today.

## Running it

Requires only Python 3 standard library (no Playwright, no pip installs). The
harness `.venv` works, or any python3.

```
# 4B execution-lane model on loopback (no key needed):
python3 benchmark/load.py --endpoint http://127.0.0.1:1238 --label 4b \
    --levels 1,2,4,8,16 --requests-per-level 24

# a private/tailnet endpoint that needs an API key: pass it via env ONLY,
# never on the command line (it would land in shell history / process args):
LFL_LOAD_API_KEY="$(cat /path/to/api-key)" \
    python3 benchmark/load.py --endpoint http://HOST:PORT --label 35b \
    --levels 1,2,4,8 --requests-per-level 12
```

Flags: `--levels` (concurrency sweep), `--requests-per-level`, `--max-tokens`
(default 128), `--warmup` (default 2, excluded from stats), `--timeout`,
`--label`. See `load.py`'s module docstring for the full list.

## Output

- Raw per-run JSON lands in `benchmark/results/` and is **gitignored** (it
  records the live endpoint, which for the 35B run is a private tailnet host).
- The committed, human-readable writeup with the transcribed numbers and the
  limitations is `benchmark/RESULTS-LOAD.md`. Regenerate the numbers yourself;
  they are transcribed from the raw JSON, not asserted.

## Notes / limitations

- Connections go **direct**, ignoring any ambient `HTTP(S)_PROXY` (this session
  may run behind Tor); the endpoints are always loopback or private-network.
- The API key is read from `LFL_LOAD_API_KEY` only, and is never written to the
  results file, printed, or committed.
- Single dev box, one Vulkan GPU (the B70) shared with the rest of the fleet.
  Running this while a fleet timer is also hitting the same endpoint will skew
  the numbers; the committed runs were taken in a quiet window. This is a
  point-in-time capacity snapshot, not a guaranteed SLA.
