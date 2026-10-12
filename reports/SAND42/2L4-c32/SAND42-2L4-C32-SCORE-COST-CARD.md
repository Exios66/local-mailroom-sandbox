# SAND-042 · 2× L4 · client concurrency 32 (16 per replica) · n=50 × 5 specialists

**Cells reported:** 0 of 5 · **Runbook:** `sand42-2l4-c32` · **Model:** Qwen/Qwen3-8B-AWQ · L4 @ $0.80/GPU-hr

## Shared conditions

| Condition | Value |
| --- | --- |
| Engine | — · max_model_len — · max_num_seqs —/replica · max_inputs — |
| Fleet | 2 replica(s) · client concurrency 32 (16 per replica) |
| Dataset | `—`  @ —, split=—, seed —, one class bucket, 50 per class stratified over every subclass (min 1 per sub-type) |
| Prompt | v1 `*_simplified` stems only |
| Output cap | max_tokens not captured · temperature 0.7 contracts + merger, 0.1 elsewhere |
| GPU telemetry | in-container nvidia-smi series, label `sand42-2l4-c32` |

## Per specialist

| Metric | Correspondence | Insurance Claims | Corporate Records | Contracts | Merger Agreements |
| --- | ---: | ---: | ---: | ---: | ---: |
| Quality (95% CI) | not run | not run | not run | not run | not run |
| Scored documents | not run | not run | not run | not run | not run |
| Quality SD | not run | not run | not run | not run | not run |
| Scoring method | not run | not run | not run | not run | not run |
| Clause metric | not run | not run | not run | not run | not run |
| Ok rate (Wilson) | not run | not run | not run | not run | not run |
| Schema-valid rate | not run | not run | not run | not run | not run |
| Parse errors | not run | not run | not run | not run | not run |
| Length-capped | not run | not run | not run | not run | not run |
| Error kinds | not run | not run | not run | not run | not run |
| p50 latency (s) | not run | not run | not run | not run | not run |
| p95 latency (s) | not run | not run | not run | not run | not run |
| SLO (s) · met | not run | not run | not run | not run | not run |
| Documents/min | not run | not run | not run | not run | not run |
| Documents/min/GPU | not run | not run | not run | not run | not run |
| Goodput docs/min/GPU | not run | not run | not run | not run | not run |
| Tokens/s/GPU | not run | not run | not run | not run | not run |
| Mean TTFT (s) | not run | not run | not run | not run | not run |
| Prefix-cache hit | not run | not run | not run | not run | not run |
| Wall (s) | not run | not run | not run | not run | not run |
| Billed GPU $ (run) | not run | not run | not run | not run | not run |
| $ / 1k ok docs | not run | not run | not run | not run | not run |
| $ / 1k schema-valid | not run | not run | not run | not run | not run |
| $ / doc | not run | not run | not run | not run | not run |
| $ / ok doc | not run | not run | not run | not run | not run |
| $ / 1M tokens | not run | not run | not run | not run | not run |
| GPU util (mean/p95/min–max) | not run | not run | not run | not run | not run |
| GPU mem used (mean) | not run | not run | not run | not run | not run |
| GPU mem bandwidth (mean) | not run | not run | not run | not run | not run |
| Sampling coverage | not run | not run | not run | not run | not run |
| GPU power (W, mean) | not run | not run | not run | not run | not run |
| GPU temp (C, mean) | not run | not run | not run | not run | not run |
| KV cache use (max %) | not run | not run | not run | not run | not run |
| Preemptions | not run | not run | not run | not run | not run |
| Length finishes | not run | not run | not run | not run | not run |

## Cost (computed from the session)

Fleet window not recorded (no fleet_window.json for this cell). Per-run costs still come from each run's own container-telemetry window.

## Per-run cards

| Specialist | Run ID | Card |
| --- | --- | --- |
| Correspondence | `sand42-50-correspondence-specialist-awq-2l4-c32` | not run |
| Insurance Claims | `sand42-50-insurance-claims-specialist-awq-2l4-c32` | not run |
| Corporate Records | `sand42-50-corporate-records-specialist-awq-2l4-c32` | not run |
| Contracts | `sand42-50-contracts-specialist-awq-2l4-c32` | not run |
| Merger Agreements | `sand42-50-merger-specialist-awq-2l4-c32` | not run |

_Merger dominates pooled throughput (≈ 112k prompt tokens per agreement on the frozen settings), so no pooled column is reported here — compare per class._

_Generated 2026-10-12T16:13:19+00:00 by `sandbox run card --runbook sand42-2l4-c32` from the committed per-run `*.card.json`._
