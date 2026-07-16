#!/usr/bin/env python3
"""benchmark/load.py - lfl-lab capacity load test.

Measures the honest serving capacity of a local llama.cpp / OpenAI-compatible
endpoint under N concurrent clients, for the hosted-gateway design's capacity
question ("how many people can one B70 actually serve"). It fires
brainstorm-style chat-completion requests - the same SHAPE of request the
lfl-terminal brainstorm/execution lanes make - and records throughput, latency
percentiles, and how latency degrades as concurrency rises.

WHAT THIS MEASURES, HONESTLY
----------------------------
Both production models this bench targets are started with `--parallel 1`
(a SINGLE decode slot). That means concurrent requests do NOT run in parallel:
the server accepts them, then services them one at a time. So the numbers here
are SEQUENTIAL / SERIALIZED throughput under load, NOT parallel throughput:

  - At concurrency 1, latency is the pure per-request service time and
    throughput is 1 / service_time.
  - As concurrency N rises, aggregate throughput (req/s) stays roughly FLAT
    (the single slot is already the bottleneck) while per-request latency
    grows roughly linearly with N, because request k waits behind the ~N-1
    others already queued at the server.

That degradation curve IS the capacity answer: it is what turns "dozens
comfortable, 100+ fragile" from a guess into a measured p50/p95-vs-N curve for
a specific model on this specific box. It is not, and does not claim to be, a
measurement of a multi-slot / batched server (that would need `--parallel >1`
and continuous batching, a different deployment and a different test).

CONFIGURATION
-------------
  --endpoint URL         base URL (default http://127.0.0.1:1238). The model
                         tag is read live from {endpoint}/v1/models and stored
                         in the raw results file (which is gitignored).
  --levels "1,2,4,8"     comma-separated concurrency levels to sweep.
  --requests-per-level N per-level request count (bumped to at least the
                         concurrency level so every worker runs at least once).
  --max-tokens N         cap on generated tokens per request (default 128).
  --warmup N             warmup requests before timing (default 2), excluded
                         from all stats - avoids cold prompt-cache / model-load
                         skew.
  --label TEXT           free-text label stored in the results file.
  --timeout S            per-request HTTP timeout (default 240).

The API key, if the endpoint needs one, is read from the LFL_LOAD_API_KEY
environment variable ONLY. It is never written to disk, never printed, and
never stored in the results file. (The loopback 4B needs none; a private
tailnet endpoint may.)

Connections go DIRECT, ignoring any ambient HTTP(S)_PROXY (this session may run
behind Tor) - these endpoints are always loopback or private-network addresses,
same as harness/runner.py and proxy/lfl-proxy.py do it.

Run:
  python3 benchmark/load.py --endpoint http://127.0.0.1:1238 --label 4b
"""
import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BENCH_DIR / "results"

# A brainstorm-style request: a short system prompt plus a "draft me a small
# automation" user turn, the same request SHAPE the terminal's lanes make. Kept
# fixed so every run and every model sees identical input; the actual generated
# length is captured per request (models may stop early on EOS), so throughput
# is reported from real token counts, not assumed ones.
SYSTEM_PROMPT = (
    "You are a terminal assistant. Given a short goal, propose a concise, "
    "step-by-step plan using only simple navigate/search/open/fill steps. "
    "Keep it under ten steps."
)
USER_PROMPT = (
    "Goal: on a shopping site, search for a product, open the first result, "
    "and add it to the cart. Draft the step-by-step plan."
)


def direct_opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def read_model_tag(endpoint):
    try:
        with direct_opener().open(f"{endpoint}/v1/models", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        models = data.get("data") or data.get("models") or []
        if models:
            ident = models[0].get("id") or models[0].get("name") or "model"
            return Path(ident).name if "/" in ident else ident
    except Exception as exc:  # noqa: BLE001
        return f"unreachable ({exc.__class__.__name__})"
    return "unknown"


def build_body(model, max_tokens):
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "stream": False,
    }


def one_request(endpoint, body_bytes, api_key, timeout):
    req = urllib.request.Request(
        f"{endpoint}/v1/chat/completions",
        data=body_bytes,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    start = time.monotonic()
    try:
        with direct_opener().open(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", "replace"))
        end = time.monotonic()
        usage = payload.get("usage") or {}
        timings = payload.get("timings") or {}
        return {
            "ok": True,
            "start": start,
            "end": end,
            "latency_s": end - start,
            "completion_tokens": usage.get("completion_tokens"),
            "prompt_tokens": usage.get("prompt_tokens"),
            "predicted_per_second": timings.get("predicted_per_second"),
        }
    except urllib.error.HTTPError as exc:
        end = time.monotonic()
        return {"ok": False, "start": start, "end": end, "latency_s": end - start,
                "error": f"HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        end = time.monotonic()
        return {"ok": False, "start": start, "end": end, "latency_s": end - start,
                "error": f"{exc.__class__.__name__}: {exc}"}


def pct(values, p):
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    # linear-interpolation percentile
    k = (len(s) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def run_level(endpoint, model, concurrency, n_requests, max_tokens, api_key, timeout):
    body_bytes = json.dumps(build_body(model, max_tokens)).encode()
    n_requests = max(n_requests, concurrency)
    results = []
    level_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(one_request, endpoint, body_bytes, api_key, timeout)
            for _ in range(n_requests)
        ]
        for fut in futures:
            results.append(fut.result())
    level_end = time.monotonic()

    ok = [r for r in results if r["ok"]]
    errs = [r for r in results if not r["ok"]]
    lat = [r["latency_s"] for r in ok]

    # Wall time across the actually-issued requests (first start to last end);
    # the ThreadPoolExecutor wall works too, but request-boundary wall is the
    # honest denominator for throughput.
    if ok:
        wall = max(r["end"] for r in ok) - min(r["start"] for r in ok)
    else:
        wall = level_end - level_start
    wall = max(wall, 1e-9)

    comp_tokens = [r["completion_tokens"] for r in ok if r.get("completion_tokens") is not None]
    total_comp = sum(comp_tokens) if comp_tokens else 0

    summary = {
        "concurrency": concurrency,
        "requests_issued": n_requests,
        "requests_ok": len(ok),
        "requests_error": len(errs),
        "error_rate": len(errs) / n_requests if n_requests else 0.0,
        "wall_s": round(wall, 3),
        "throughput_req_s": round(len(ok) / wall, 4) if ok else 0.0,
        "throughput_tok_s": round(total_comp / wall, 2) if total_comp else None,
        "latency_p50_s": round(pct(lat, 50), 3) if lat else None,
        "latency_p95_s": round(pct(lat, 95), 3) if lat else None,
        "latency_p99_s": round(pct(lat, 99), 3) if lat else None,
        "latency_min_s": round(min(lat), 3) if lat else None,
        "latency_max_s": round(max(lat), 3) if lat else None,
        "latency_mean_s": round(statistics.mean(lat), 3) if lat else None,
        "mean_completion_tokens": round(statistics.mean(comp_tokens), 1) if comp_tokens else None,
        "error_samples": [e.get("error") for e in errs[:3]],
    }
    return summary


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--endpoint", default=os.environ.get("LFL_LOAD_ENDPOINT", "http://127.0.0.1:1238"))
    ap.add_argument("--levels", default="1,2,4,8")
    ap.add_argument("--requests-per-level", type=int, default=16)
    ap.add_argument("--max-tokens", type=int, default=128)
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--label", default="")
    ap.add_argument("--timeout", type=float, default=240.0)
    args = ap.parse_args()

    endpoint = args.endpoint.rstrip("/")
    levels = [int(x) for x in args.levels.split(",") if x.strip()]
    api_key = os.environ.get("LFL_LOAD_API_KEY") or None

    model = read_model_tag(endpoint)
    print(f"[setup] endpoint={endpoint}  model_tag={model}  levels={levels}  "
          f"requests/level={args.requests_per_level}  max_tokens={args.max_tokens}  "
          f"auth={'yes' if api_key else 'no'}")
    if model.startswith("unreachable"):
        sys.stderr.write("ERROR: endpoint /v1/models unreachable; aborting.\n")
        return 2

    body_bytes = json.dumps(build_body(model, args.max_tokens)).encode()
    for i in range(max(0, args.warmup)):
        r = one_request(endpoint, body_bytes, api_key, args.timeout)
        print(f"[warmup {i+1}/{args.warmup}] ok={r['ok']} latency={r['latency_s']:.2f}s"
              + ("" if r["ok"] else f"  ({r.get('error')})"))

    level_summaries = []
    for n in levels:
        print(f"[level] concurrency={n} ...", flush=True)
        s = run_level(endpoint, model, n, args.requests_per_level, args.max_tokens, api_key, args.timeout)
        level_summaries.append(s)
        print(f"        ok={s['requests_ok']}/{s['requests_issued']}  "
              f"throughput={s['throughput_req_s']} req/s  "
              f"tok/s={s['throughput_tok_s']}  "
              f"p50={s['latency_p50_s']}s  p95={s['latency_p95_s']}s  "
              f"errors={s['requests_error']}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_path = RESULTS_DIR / f"load-{ts}-{args.label or model}.json"
    out = {
        "timestamp_utc": ts,
        "endpoint": endpoint,
        "model_tag": model,
        "label": args.label,
        "max_tokens": args.max_tokens,
        "requests_per_level": args.requests_per_level,
        "warmup": args.warmup,
        "note": "single-slot (--parallel 1) server: this measures serialized "
                "service under concurrency, not parallel throughput.",
        "levels": level_summaries,
    }
    out_path.write_text(json.dumps(out, indent=2))

    print("\n=== summary (concurrency -> throughput / latency) ===")
    print(f"{'N':>3}  {'ok':>7}  {'req/s':>7}  {'tok/s':>7}  {'p50 s':>7}  {'p95 s':>7}  {'p99 s':>7}  {'errs':>4}")
    for s in level_summaries:
        print(f"{s['concurrency']:>3}  {s['requests_ok']:>3}/{s['requests_issued']:<3}  "
              f"{s['throughput_req_s']:>7}  {str(s['throughput_tok_s']):>7}  "
              f"{str(s['latency_p50_s']):>7}  {str(s['latency_p95_s']):>7}  "
              f"{str(s['latency_p99_s']):>7}  {s['requests_error']:>4}")
    print(f"\nraw results written to {out_path}  (gitignored)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
