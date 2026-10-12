# SAND-042 · 2× L4 · client concurrency 16 (8 per replica) · n=50 × 5 specialists

**Cells reported:** 3 of 5 · **Runbook:** `sand42-2l4-c16` · **Model:** Qwen/Qwen3-8B-AWQ · L4 @ $0.80/GPU-hr

## Shared conditions

| Condition | Value |
| --- | --- |
| Engine | — · max_model_len 32768 · max_num_seqs 16/replica · max_inputs 32 |
| Fleet | 2 replica(s) · client concurrency 16 (8 per replica) |
| Dataset | `Lucius-Morningstar/mailroom-dataset` ground_truth @ ed7576b6, split=all, seed 42, one class bucket, 50 per class stratified over every subclass (min 1 per sub-type) |
| Prompt | v1 `*_simplified` stems only |
| Output cap | max_tokens 8,192 · temperature 0.7 contracts + merger, 0.1 elsewhere |
| GPU telemetry | in-container nvidia-smi series, label `sand42-2l4-c16` |

## Per specialist

| Metric | Correspondence | Insurance Claims | Corporate Records | Contracts | Merger Agreements |
| --- | ---: | ---: | ---: | ---: | ---: |
| Quality (95% CI) | 0.382 [0.318, 0.447] | 0.668 [0.650, 0.686] | 0.498 [0.430, 0.565] | not run | not run |
| Scored documents | 50 | 50 | 50 | not run | not run |
| Quality SD | 0.237 | 0.063 | 0.247 | not run | not run |
| Scoring method | suite | suite | suite | not run | not run |
| Clause metric | — | — | — | not run | not run |
| Ok rate (Wilson) | 50/50 100.0% [0.929, 1.000] | 50/50 100.0% [0.929, 1.000] | 50/50 100.0% [0.929, 1.000] | not run | not run |
| Schema-valid rate | 100.0% | 24.0% | 98.0% | not run | not run |
| Parse errors | 0 | 0 | 0 | not run | not run |
| Length-capped | 0 | 0 | 0 | not run | not run |
| Error kinds | — | — | — | not run | not run |
| p50 latency (s) | 6.7 | 14.4 | 11.2 | not run | not run |
| p95 latency (s) | 10.8 | 22.5 | 19.1 | not run | not run |
| SLO (s) · met | 60 · yes | 60 · yes | 60 · yes | not run | not run |
| Documents/min | 75.20 | 34.89 | 55.86 | not run | not run |
| Documents/min/GPU | 75.20 | 34.89 | 55.86 | not run | not run |
| Goodput docs/min/GPU | 37.60 | 17.44 | 27.93 | not run | not run |
| Tokens/s/GPU | 1,719.0 | 1,078.8 | 1,914.0 | not run | not run |
| Mean TTFT (s) | 1.04 | 1.33 | 1.55 | not run | not run |
| Prefix-cache hit | 62.5% | 57.2% | 49.9% | not run | not run |
| Wall (s) | 39.9 | 86.0 | 53.7 | not run | not run |
| Billed GPU $ (run) | $0.0180 | $0.0385 | $0.0241 | not run | not run |
| $ / 1k ok docs | $0.359540 | $0.769340 | $0.481800 | not run | not run |
| $ / 1k schema-valid | $0.359540 | $3.205583 | $0.491633 | not run | not run |
| $ / doc | $0.000360 | $0.000769 | $0.000482 | not run | not run |
| $ / ok doc | $0.000360 | $0.000769 | $0.000482 | not run | not run |
| $ / 1M tokens | $0.131 | $0.207 | $0.117 | not run | not run |
| GPU util (mean/p95/min–max) | 63.7% mean / 98.0 p95 / 0.0–100.0% min–max (n=12) | 76.3% mean / 100.0 p95 / 0.0–100.0% min–max (n=27) | 65.4% mean / 100.0 p95 / 0.0–100.0% min–max (n=18) | not run | not run |
| GPU mem used (mean) | 19,973 MiB (86.7% of 23,034) | 19,993 MiB (86.8% of 23,034) | 19,994 MiB (86.8% of 23,034) | not run | not run |
| GPU mem bandwidth (mean) | 57.8% mean | 69.0% mean | 52.3% mean | not run | not run |
| Sampling coverage | 95.6% | 100.0% | 65.6% ⚠ below the 90% gate (issue #128) | not run | not run |
| GPU power (W, mean) | 56.8 | 62.9 | 59.8 | not run | not run |
| GPU temp (C, mean) | 62.3 | 69.8 | 74.4 | not run | not run |
| KV cache use (max %) | 0.0 | 0.0 | 0.0 | not run | not run |
| Preemptions | 0 | 0 | 0 | not run | not run |
| Length finishes | 0 | 0 | 0 | not run | not run |

## Figure

![SAND-042 2l4-c16 cell dashboard](../figures/2l4-c16-dashboard.png)

## Cost (computed from the session)

Fleet window not recorded (no fleet_window.json for this cell). Per-run costs still come from each run's own container-telemetry window.

## Per-run cards

| Specialist | Run ID | Card |
| --- | --- | --- |
| Correspondence | `sand42-50-correspondence-specialist-awq-2l4-c16` | [sand42-50-correspondence-specialist-awq-2l4-c16.card.md](correspondence/sand42-50-correspondence-specialist-awq-2l4-c16.card.md) |
| Insurance Claims | `sand42-50-insurance-claims-specialist-awq-2l4-c16` | [sand42-50-insurance-claims-specialist-awq-2l4-c16.card.md](insurance_claims/sand42-50-insurance-claims-specialist-awq-2l4-c16.card.md) |
| Corporate Records | `sand42-50-corporate-records-specialist-awq-2l4-c16` | [sand42-50-corporate-records-specialist-awq-2l4-c16.card.md](corporate_records/sand42-50-corporate-records-specialist-awq-2l4-c16.card.md) |
| Contracts | `sand42-50-contracts-specialist-awq-2l4-c16` | not run |
| Merger Agreements | `sand42-50-merger-specialist-awq-2l4-c16` | not run |

_Merger dominates pooled throughput (≈ 112k prompt tokens per agreement on the frozen settings), so no pooled column is reported here — compare per class._

_Generated 2026-10-12T07:01:17+00:00 by `sandbox run card --runbook sand42-2l4-c16` from the committed per-run `*.card.json`._
