# SAND-042 master report — full detail

Per-condition tables, engine and GPU telemetry, the paired comparison and the method. Executive summary: [`SAND42-MASTER-SCORE-COST-CARD.md`](SAND42-MASTER-SCORE-COST-CARD.md).

# SAND-042 · 1× L4 · client concurrency 8 · n=50 × 5 specialists

**Cells reported:** 0 of 5 · **Runbook:** `sand42-1l4-c8` · **Model:** Qwen/Qwen3-8B-AWQ · L4 @ $0.80/GPU-hr

## Shared conditions

| Condition | Value |
| --- | --- |
| Engine | — · max_model_len — · max_num_seqs —/replica · max_inputs — |
| Fleet | 1 replica(s) · client concurrency 8 (8 per replica) |
| Dataset | `—`  @ —, split=—, seed —, one class bucket, 50 per class stratified over every subclass (min 1 per sub-type) |
| Prompt | v1 `*_simplified` stems only |
| Output cap | max_tokens not captured · temperature 0.7 contracts + merger, 0.1 elsewhere |
| GPU telemetry | in-container nvidia-smi series, label `sand42-1l4-c8` |

## Per specialist

| Metric | Correspondence | Insurance Claims | Corporate Records | Contracts | Merger Agreements |
| --- | ---: | ---: | ---: | ---: | ---: |
| Quality (95% CI) | not run | not run | not run | not run | not run |
| Scored documents | not run | not run | not run | not run | not run |
| Scoring method | not run | not run | not run | not run | not run |
| Ok rate (Wilson) | not run | not run | not run | not run | not run |
| Schema-valid rate | not run | not run | not run | not run | not run |
| Length-capped | not run | not run | not run | not run | not run |
| p50 latency (s) | not run | not run | not run | not run | not run |
| p95 latency (s) | not run | not run | not run | not run | not run |
| SLO (s) · met | not run | not run | not run | not run | not run |
| Documents/min/GPU | not run | not run | not run | not run | not run |
| Goodput docs/min/GPU | not run | not run | not run | not run | not run |
| Tokens/s/GPU | not run | not run | not run | not run | not run |
| Wall (s) | not run | not run | not run | not run | not run |
| $ / 1k ok docs | not run | not run | not run | not run | not run |
| $ / 1k schema-valid | not run | not run | not run | not run | not run |
| GPU util (mean/peak) | not run | not run | not run | not run | not run |
| GPU power (W, mean) | not run | not run | not run | not run | not run |
| GPU temp (C, mean) | not run | not run | not run | not run | not run |
| KV cache use (max %) | not run | not run | not run | not run | not run |
| Preemptions | not run | not run | not run | not run | not run |
| Length finishes | not run | not run | not run | not run | not run |

## Per-run cards

| Specialist | Run ID | Card |
| --- | --- | --- |
| Correspondence | `sand42-50-correspondence-specialist-awq-1l4-c8` | not run |
| Insurance Claims | `sand42-50-insurance-claims-specialist-awq-1l4-c8` | not run |
| Corporate Records | `sand42-50-corporate-records-specialist-awq-1l4-c8` | not run |
| Contracts | `sand42-50-contracts-specialist-awq-1l4-c8` | not run |
| Merger Agreements | `sand42-50-merger-specialist-awq-1l4-c8` | not run |

_Merger dominates pooled throughput (≈ 112k prompt tokens per agreement on the frozen settings), so no pooled column is reported here — compare per class._

_Generated 2026-10-12T00:11:20+00:00 by `sandbox run card --runbook sand42-1l4-c8` from the committed per-run `*.card.json`._


---

# SAND-042 · 1× L4 · client concurrency 16 · n=50 × 5 specialists

**Cells reported:** 0 of 5 · **Runbook:** `sand42-1l4-c16` · **Model:** Qwen/Qwen3-8B-AWQ · L4 @ $0.80/GPU-hr

## Shared conditions

| Condition | Value |
| --- | --- |
| Engine | — · max_model_len — · max_num_seqs —/replica · max_inputs — |
| Fleet | 1 replica(s) · client concurrency 16 (16 per replica) |
| Dataset | `—`  @ —, split=—, seed —, one class bucket, 50 per class stratified over every subclass (min 1 per sub-type) |
| Prompt | v1 `*_simplified` stems only |
| Output cap | max_tokens not captured · temperature 0.7 contracts + merger, 0.1 elsewhere |
| GPU telemetry | in-container nvidia-smi series, label `sand42-1l4-c16` |

## Per specialist

| Metric | Correspondence | Insurance Claims | Corporate Records | Contracts | Merger Agreements |
| --- | ---: | ---: | ---: | ---: | ---: |
| Quality (95% CI) | not run | not run | not run | not run | not run |
| Scored documents | not run | not run | not run | not run | not run |
| Scoring method | not run | not run | not run | not run | not run |
| Ok rate (Wilson) | not run | not run | not run | not run | not run |
| Schema-valid rate | not run | not run | not run | not run | not run |
| Length-capped | not run | not run | not run | not run | not run |
| p50 latency (s) | not run | not run | not run | not run | not run |
| p95 latency (s) | not run | not run | not run | not run | not run |
| SLO (s) · met | not run | not run | not run | not run | not run |
| Documents/min/GPU | not run | not run | not run | not run | not run |
| Goodput docs/min/GPU | not run | not run | not run | not run | not run |
| Tokens/s/GPU | not run | not run | not run | not run | not run |
| Wall (s) | not run | not run | not run | not run | not run |
| $ / 1k ok docs | not run | not run | not run | not run | not run |
| $ / 1k schema-valid | not run | not run | not run | not run | not run |
| GPU util (mean/peak) | not run | not run | not run | not run | not run |
| GPU power (W, mean) | not run | not run | not run | not run | not run |
| GPU temp (C, mean) | not run | not run | not run | not run | not run |
| KV cache use (max %) | not run | not run | not run | not run | not run |
| Preemptions | not run | not run | not run | not run | not run |
| Length finishes | not run | not run | not run | not run | not run |

## Per-run cards

| Specialist | Run ID | Card |
| --- | --- | --- |
| Correspondence | `sand42-50-correspondence-specialist-awq-1l4-c16` | not run |
| Insurance Claims | `sand42-50-insurance-claims-specialist-awq-1l4-c16` | not run |
| Corporate Records | `sand42-50-corporate-records-specialist-awq-1l4-c16` | not run |
| Contracts | `sand42-50-contracts-specialist-awq-1l4-c16` | not run |
| Merger Agreements | `sand42-50-merger-specialist-awq-1l4-c16` | not run |

_Merger dominates pooled throughput (≈ 112k prompt tokens per agreement on the frozen settings), so no pooled column is reported here — compare per class._

_Generated 2026-10-12T00:11:20+00:00 by `sandbox run card --runbook sand42-1l4-c16` from the committed per-run `*.card.json`._


---

# SAND-042 · 2× L4 · client concurrency 8 (4 per replica) · n=50 × 5 specialists

**Cells reported:** 0 of 5 · **Runbook:** `sand42-2l4-c8` · **Model:** Qwen/Qwen3-8B-AWQ · L4 @ $0.80/GPU-hr

## Shared conditions

| Condition | Value |
| --- | --- |
| Engine | — · max_model_len — · max_num_seqs —/replica · max_inputs — |
| Fleet | 2 replica(s) · client concurrency 8 (4 per replica) |
| Dataset | `—`  @ —, split=—, seed —, one class bucket, 50 per class stratified over every subclass (min 1 per sub-type) |
| Prompt | v1 `*_simplified` stems only |
| Output cap | max_tokens not captured · temperature 0.7 contracts + merger, 0.1 elsewhere |
| GPU telemetry | in-container nvidia-smi series, label `sand42-2l4-c8` |

## Per specialist

| Metric | Correspondence | Insurance Claims | Corporate Records | Contracts | Merger Agreements |
| --- | ---: | ---: | ---: | ---: | ---: |
| Quality (95% CI) | not run | not run | not run | not run | not run |
| Scored documents | not run | not run | not run | not run | not run |
| Scoring method | not run | not run | not run | not run | not run |
| Ok rate (Wilson) | not run | not run | not run | not run | not run |
| Schema-valid rate | not run | not run | not run | not run | not run |
| Length-capped | not run | not run | not run | not run | not run |
| p50 latency (s) | not run | not run | not run | not run | not run |
| p95 latency (s) | not run | not run | not run | not run | not run |
| SLO (s) · met | not run | not run | not run | not run | not run |
| Documents/min/GPU | not run | not run | not run | not run | not run |
| Goodput docs/min/GPU | not run | not run | not run | not run | not run |
| Tokens/s/GPU | not run | not run | not run | not run | not run |
| Wall (s) | not run | not run | not run | not run | not run |
| $ / 1k ok docs | not run | not run | not run | not run | not run |
| $ / 1k schema-valid | not run | not run | not run | not run | not run |
| GPU util (mean/peak) | not run | not run | not run | not run | not run |
| GPU power (W, mean) | not run | not run | not run | not run | not run |
| GPU temp (C, mean) | not run | not run | not run | not run | not run |
| KV cache use (max %) | not run | not run | not run | not run | not run |
| Preemptions | not run | not run | not run | not run | not run |
| Length finishes | not run | not run | not run | not run | not run |

## Per-run cards

| Specialist | Run ID | Card |
| --- | --- | --- |
| Correspondence | `sand42-50-correspondence-specialist-awq-2l4-c8` | not run |
| Insurance Claims | `sand42-50-insurance-claims-specialist-awq-2l4-c8` | not run |
| Corporate Records | `sand42-50-corporate-records-specialist-awq-2l4-c8` | not run |
| Contracts | `sand42-50-contracts-specialist-awq-2l4-c8` | not run |
| Merger Agreements | `sand42-50-merger-specialist-awq-2l4-c8` | not run |

_Merger dominates pooled throughput (≈ 112k prompt tokens per agreement on the frozen settings), so no pooled column is reported here — compare per class._

_Generated 2026-10-12T00:11:20+00:00 by `sandbox run card --runbook sand42-2l4-c8` from the committed per-run `*.card.json`._


---

# SAND-042 · 2× L4 · client concurrency 16 (8 per replica) · n=50 × 5 specialists

**Cells reported:** 0 of 5 · **Runbook:** `sand42-2l4-c16` · **Model:** Qwen/Qwen3-8B-AWQ · L4 @ $0.80/GPU-hr

## Shared conditions

| Condition | Value |
| --- | --- |
| Engine | — · max_model_len — · max_num_seqs —/replica · max_inputs — |
| Fleet | 2 replica(s) · client concurrency 16 (8 per replica) |
| Dataset | `—`  @ —, split=—, seed —, one class bucket, 50 per class stratified over every subclass (min 1 per sub-type) |
| Prompt | v1 `*_simplified` stems only |
| Output cap | max_tokens not captured · temperature 0.7 contracts + merger, 0.1 elsewhere |
| GPU telemetry | in-container nvidia-smi series, label `sand42-2l4-c16` |

## Per specialist

| Metric | Correspondence | Insurance Claims | Corporate Records | Contracts | Merger Agreements |
| --- | ---: | ---: | ---: | ---: | ---: |
| Quality (95% CI) | not run | not run | not run | not run | not run |
| Scored documents | not run | not run | not run | not run | not run |
| Scoring method | not run | not run | not run | not run | not run |
| Ok rate (Wilson) | not run | not run | not run | not run | not run |
| Schema-valid rate | not run | not run | not run | not run | not run |
| Length-capped | not run | not run | not run | not run | not run |
| p50 latency (s) | not run | not run | not run | not run | not run |
| p95 latency (s) | not run | not run | not run | not run | not run |
| SLO (s) · met | not run | not run | not run | not run | not run |
| Documents/min/GPU | not run | not run | not run | not run | not run |
| Goodput docs/min/GPU | not run | not run | not run | not run | not run |
| Tokens/s/GPU | not run | not run | not run | not run | not run |
| Wall (s) | not run | not run | not run | not run | not run |
| $ / 1k ok docs | not run | not run | not run | not run | not run |
| $ / 1k schema-valid | not run | not run | not run | not run | not run |
| GPU util (mean/peak) | not run | not run | not run | not run | not run |
| GPU power (W, mean) | not run | not run | not run | not run | not run |
| GPU temp (C, mean) | not run | not run | not run | not run | not run |
| KV cache use (max %) | not run | not run | not run | not run | not run |
| Preemptions | not run | not run | not run | not run | not run |
| Length finishes | not run | not run | not run | not run | not run |

## Per-run cards

| Specialist | Run ID | Card |
| --- | --- | --- |
| Correspondence | `sand42-50-correspondence-specialist-awq-2l4-c16` | not run |
| Insurance Claims | `sand42-50-insurance-claims-specialist-awq-2l4-c16` | not run |
| Corporate Records | `sand42-50-corporate-records-specialist-awq-2l4-c16` | not run |
| Contracts | `sand42-50-contracts-specialist-awq-2l4-c16` | not run |
| Merger Agreements | `sand42-50-merger-specialist-awq-2l4-c16` | not run |

_Merger dominates pooled throughput (≈ 112k prompt tokens per agreement on the frozen settings), so no pooled column is reported here — compare per class._

_Generated 2026-10-12T00:11:20+00:00 by `sandbox run card --runbook sand42-2l4-c16` from the committed per-run `*.card.json`._


---

# SAND-042 · paired comparison across the four cells

All four cells score the **identical 250 documents** (5 specialists × 50, one subclass-stratified draw), so every cell-to-cell delta below is **paired**: the unit of analysis is the per-document score difference. Intervals are 95% percentile bootstrap over documents; the last column is the paired n that Δ = 0.05 would need at 80% power.

Reference cell: **1l4-c8** (1×L4, client concurrency 8).

## 1l4-c16 (1× L4 · C16) vs 1l4-c8

| Class | Paired n | Δ mean | 95% CI | SD_diff | better / worse / tie | n for Δ=0.05 |
| --- | ---: | ---: | --- | ---: | --- | ---: |
| _not run yet_ | | | | | | |

## 2l4-c8 (2× L4 · C8 · 4/replica) vs 1l4-c8

| Class | Paired n | Δ mean | 95% CI | SD_diff | better / worse / tie | n for Δ=0.05 |
| --- | ---: | ---: | --- | ---: | --- | ---: |
| _not run yet_ | | | | | | |

## 2l4-c16 (2× L4 · C16 · 8/replica) vs 1l4-c8

| Class | Paired n | Δ mean | 95% CI | SD_diff | better / worse / tie | n for Δ=0.05 |
| --- | ---: | ---: | --- | ---: | --- | ---: |
| _not run yet_ | | | | | | |

## Noise floor (run-to-run, same 50 documents)

_Not measured._ Run `sand42-noise-floor` (blocked until spend is approved) on the same 50 correspondence documents. Until then the SAND-037/39 floor in `docs/BENCHMARK-PROGRAM.md` §3 is the prior — it was measured on a different draw, so treat it as indicative only.

_Generated 2026-10-12T00:11:20+00:00 by `sandbox run card --runbook sand42`._


---

## Method

* Engine, prompts, decode, dataset pin and draw are identical across the four conditions; only the replica count and the client concurrency differ (asserted in `tests/test_sand42_grid.py`).
* Client concurrency is split equally across replicas: 2×L4 C8 → 4 per replica, 2×L4 C16 → 8 per replica.
* One warm fleet per condition (`min_containers = max_containers = replicas`), five specialists chained, teardown after the fifth: one cold boot per condition.
* Quality intervals are percentile bootstraps over per-document scores; deltas are paired on the shared 250 documents; ok rates use a Wilson interval.
* GPU hardware telemetry is sampled inside the serving replica (nvidia-smi util / power / temperature / memory) and recorded per condition; vLLM `/metrics` gives the engine side (TTFT, prefix-cache hit rate, preemptions, length finishes, KV use) per replica.
* Sample sizes, the noise floor and the contracts caveat: `docs/BENCHMARK-PROGRAM.md` §3 and `docs/SAND42-EXPERIMENT-DESIGN.md` §4.

## Open items

* The noise-floor leg (`sand42-noise-floor`) is blocked pending spend; until it runs the SAND-037/39 floor is a prior measured on a different draw.
* Contracts at n=50 paired is marginal for Δ=0.05 and unpowered for Δ=0.03 — report as an interval, never a ranking.
* OTel *metrics* export from the container is not wired (the telemetry is an nvidia-smi series); trace spans stay opt-in via `trace.sink`.

_Generated 2026-10-12T00:11:20+00:00 by `sandbox run card --runbook sand42`._
