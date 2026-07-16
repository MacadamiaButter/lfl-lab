# RESULTS-LOAD - capacity under concurrency (measured, not guessed)

This is the empirical answer to the hosted-gateway design's capacity question:
how many concurrent users can one local model endpoint on this box actually
serve, and how does latency degrade as that number climbs. It turns the design
doc's placeholder guess ("dozens comfortable per B70, 100+ fragile") into a
measured degradation curve for two real models on the real hardware.

Read the LIMITATIONS at the bottom as part of the result. Regenerate every
number yourself with `benchmark/load.py` (see `benchmark/README.md`); the raw
per-run JSON lands in `benchmark/results/` (gitignored) and the numbers below
are transcribed from it, not asserted.

## What was measured

- **Load tool:** `benchmark/load.py`, a dependency-free harness that fires
  brainstorm-style chat-completion requests (the same request *shape* the
  terminal's lanes make) at an OpenAI-compatible endpoint under a sweep of
  concurrency levels, and records throughput, latency percentiles, and error
  rate at each level. Fixed prompt, `max_tokens=128`, two warmup requests per
  run excluded from the stats.
- **4B execution-lane model:** `Qwen3-4B-Instruct-2507-Q5_K_M` on `127.0.0.1:1238`,
  24 requests per level, levels 1/2/4/8/16.
- **35B brainstorm-lane model:** `Qwen3.6-35B-A3B` (Q5_K_M) on the private
  tailnet endpoint `:1236`, 12 requests per level, levels 1/2/4/8.
- One dev box, one Vulkan GPU (the B70) shared with the rest of the fleet, taken
  in a quiet window with no heavy fleet timer firing. 2026-07-16 (UTC).

## The single most important config fact

The two servers are configured differently, and that difference *is* the result:

- The **35B** is launched with `--parallel 1` - a **single decode slot**.
  Concurrent requests do not run in parallel; the server services them one at a
  time. This is genuine serialized-under-load behavior.
- The **4B** is launched with **no** `--parallel` flag, and this llama.cpp build
  then defaults to **4 slots** (its own startup log: `n_slots = 4,
  n_ctx_slot = 4096, kv_unified = 'true'`). So the 4B genuinely batches a few
  concurrent requests before it saturates.

Neither is a large multi-slot production deployment. This measures the endpoints
exactly as the fleet runs them today.

## 4B execution lane (`n_slots = 4`)

| concurrency | throughput (req/s) | agg tok/s | p50 (s) | p95 (s) | p99 (s) | errors |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.85 | 53 | 1.18 | 1.38 | 1.40 | 0 |
| 2 | 1.39 | 93 | 1.49 | 1.52 | 1.58 | 0 |
| 4 | 2.10 | 135 | 1.83 | 2.30 | 2.37 | 0 |
| 8 | 2.01 | 123 | 3.30 | 5.09 | 5.12 | 0 |
| 16 | 1.97 | 131 | 6.66 | 8.03 | 8.43 | 0 |

The 4B extracts real batching gains up to its slot count: throughput rises from
0.85 req/s at concurrency 1 to a ceiling of about **2.0 req/s at concurrency 4**
(roughly 2.5x), with p50 latency still near 1.8s. Past 4 concurrent the slots
are full: throughput stops improving and latency grows roughly linearly instead
(p50 ~3.3s at 8, ~6.7s at 16). Zero errors throughout. Mean generated length was
about 62-67 tokens (the model hits its EOS before the 128 cap), so the tok/s
column is real generated tokens, not padded to the cap.

Practical read: the execution lane comfortably serves a handful of genuinely
concurrent users at low-single-digit-second latency, with graceful (not
cliff-edged) degradation beyond that.

## 35B brainstorm lane (`--parallel 1`, single slot)

| concurrency | throughput (req/s) | agg tok/s | p50 (s) | p95 (s) | p99 (s) | errors |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.46 | 35 | 2.09 | 2.60 | 2.67 | 0 |
| 2 | 0.45 | 32 | 4.15 | 5.45 | 5.57 | 0 |
| 4 | 0.55 | 35 | 7.07 | 7.49 | 7.60 | 0 |
| 8 | 0.50 | 34 | 12.84 | 16.54 | 16.99 | 0 |

This is the textbook single-slot signature and the exact opposite of the 4B's
curve: aggregate throughput is **flat at about 0.5 req/s regardless of
concurrency** (the one slot is the ceiling from the start), while per-request
latency grows **linearly** with the number of concurrent clients - p50 doubles
from 1 to 2 clients (2.1s -> 4.2s) and reaches ~12.8s (p95 ~16.5s) at 8
concurrent, because request k simply waits behind the k-1 requests already
queued at the slot. Zero errors: nothing dropped, everyone just waited their
turn. Aggregate token throughput sat around 33-35 tok/s the whole time,
consistent with one sequence decoding at a time.

## What this means for the hosted-gateway design

The design doc (`LFL-HOSTED-GATEWAY-DESIGN.md`) guessed "dozens comfortable per
B70, 100+ fragile" and flagged "single-GPU throughput low, meter hard, do not
sell flat-unlimited." The measured numbers **support the caution and sharpen
it**:

- The **35B premium/brainstorm lane, as configured today (`--parallel 1`), is
  genuinely low-capacity for interactive use.** Sustained throughput is ~0.5
  req/s (~30 requests/minute), and because latency grows linearly with
  concurrency, even 8 simultaneous users see ~13s median / ~17s p95 for a short
  128-token generation. Real brainstorm outputs (a full script body) are longer
  and would be slower still. "Dozens comfortable, concurrently, on the 35B" is
  **not** supportable at one slot; the honest ceiling is low single-digit
  concurrent users before p95 latency becomes painful. This directly backs the
  design's decision to keep brainstorm a capped beta / waitlist and to meter
  rather than sell flat-unlimited, and it argues for either `--parallel > 1`
  (trading per-request speed and KV memory for concurrency) or the milestone
  second GPU before the 35B lane opens broadly.
- The **4B execution lane has roughly 4x the concurrency headroom** on the same
  box (a ~2 req/s ceiling versus ~0.5), consistent with it being the free /
  small tier that most requests hit.
- "Comfortable" is a latency budget choice, not a hard number. If the budget is
  "p95 under ~3s," the 4B is comfortable to about 4 concurrent and the 35B to
  about 1. If the budget is "p95 under ~8s," the 4B stretches past 16 and the
  35B to about 4. The curve, not a single headline number, is the deliverable.

## LIMITATIONS (read as part of the result)

- **Point-in-time, shared-GPU snapshot.** One box, one Vulkan GPU shared with
  the live fleet, one quiet window. A fleet timer hitting the same endpoint mid-
  run would skew it; these runs were taken with no heavy consumer firing. This
  is not a guaranteed SLA.
- **128-token generations.** `max_tokens=128` bounds each request; real
  brainstorm-lane outputs (a full multi-step script) are often longer, which
  would lower req/s and raise latency versus these numbers. Treat these as an
  optimistic-ish ceiling for the request shape, not a worst case.
- **The two models were run at their as-deployed slot counts, not matched.** The
  4B had 4 slots (build default) and the 35B had 1 (`--parallel 1`). This is a
  fair picture of *today's deployment*, but it is not an apples-to-apples
  per-slot efficiency comparison of the two models. A matched `--parallel`
  comparison is a separate test not done here.
- **Throughput is wall-clock request completion, latency is client-observed.**
  The client fires N concurrent requests via a thread pool; each request's
  latency includes its time queued at the server. No streaming / time-to-first-
  token measurement here - this is end-to-end completion latency for a bounded
  generation.
- **Not a multi-slot / continuous-batching production benchmark.** Raising
  `--parallel`, enabling larger batch sizes, or adding a second GPU are exactly
  the levers the gateway design contemplates; this measures the current fleet
  config, which is the honest baseline those changes would be measured against.
