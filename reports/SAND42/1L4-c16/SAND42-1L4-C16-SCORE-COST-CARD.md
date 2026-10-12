# SAND-042 · 1× L4 · client concurrency 16 · n=50 × 5 specialists

**Cells reported:** 4 of 5 · **Runbook:** `sand42-1l4-c16` · **Model:** Qwen/Qwen3-8B-AWQ · L4 @ $0.80/GPU-hr

## Shared conditions

| Condition | Value |
| --- | --- |
| Engine | — · max_model_len 32768 · max_num_seqs 16/replica · max_inputs 32 |
| Fleet | 1 replica(s) · client concurrency 16 (16 per replica) |
| Dataset | `Lucius-Morningstar/mailroom-dataset` ground_truth @ ed7576b6, split=all, seed 42, one class bucket, 50 per class stratified over every subclass (min 1 per sub-type) |
| Prompt | v1 `*_simplified` stems only |
| Output cap | max_tokens 8,192 · temperature 0.7 contracts + merger, 0.1 elsewhere |
| GPU telemetry | in-container nvidia-smi series, label `sand42-1l4-c16` |

## Per specialist

| Metric | Correspondence | Insurance Claims | Corporate Records | Contracts | Merger Agreements |
| --- | ---: | ---: | ---: | ---: | ---: |
| Quality (95% CI) | 0.381 [0.313, 0.447] | 0.665 [0.647, 0.683] | 0.484 [0.413, 0.553] | 0.603 [0.565, 0.642] | not run |
| Scored documents | 50 | 50 | 50 | 45 | not run |
| Scoring method | suite | suite | suite | suite+cuad | not run |
| Ok rate (Wilson) | 50/50 100.0% [0.929, 1.000] | 50/50 100.0% [0.929, 1.000] | 50/50 100.0% [0.929, 1.000] | 50/50 100.0% [0.929, 1.000] | not run |
| Schema-valid rate | 100.0% | 28.0% | 96.0% | 100.0% | not run |
| Length-capped | 0 | 0 | 0 | 0 | not run |
| p50 latency (s) | 9.4 | 20.5 | 19.6 | 176.2 | not run |
| p95 latency (s) | 14.0 | 30.3 | 24.3 | 914.4 | not run |
| SLO (s) · met | 60 · yes | 60 · yes | 60 · yes | 300 · no | not run |
| Documents/min/GPU | 130.35 | 472.22 | 71.96 | 2.96 | not run |
| Goodput docs/min/GPU | 130.35 | 472.22 | 71.96 | 0.00 | not run |
| Tokens/s/GPU | 5,966.5 | 29,287.6 | 4,924.8 | 920.8 | not run |
| Wall (s) | 23.0 | 6.4 | 41.7 | 1,012.0 | not run |
| Billed GPU $ (run) | $0.0140 | $0.0268 | $0.0206 | $0.2541 | not run |
| $ / 1k ok docs | $0.279800 | $0.536440 | $0.412340 | $5.082960 | not run |
| $ / 1k schema-valid | $0.279800 | $1.915857 | $0.429521 | $5.082960 | not run |
| GPU util (mean/p95/peak) | 44.4% mean / 100.0 p95 / 100.0% peak (n=11) | 74.6% mean / 100.0 p95 / 100.0% peak (n=21) | 67.8% mean / 100.0 p95 / 100.0% peak (n=16) | 94.5% mean / 100.0 p95 / 100.0% peak (n=167) | not run |
| GPU mem used (mean) | 21,002 MiB (91.2% of 23,034) | 21,025 MiB (91.3% of 23,034) | 21,026 MiB (91.3% of 23,034) | 21,024 MiB (91.3% of 23,034) | not run |
| GPU mem bandwidth (mean) | 38.9% mean | 66.9% mean | 47.2% mean | 84.7% mean | not run |
| Sampling coverage | 100.0% | 100.0% | 100.0% | 88.4% ⚠ below the 90% gate (issue #128) | not run |
| GPU power (W, mean) | 51.0 | 61.7 | 59.2 | 70.5 | not run |
| GPU temp (C, mean) | 73.6 | 75.2 | 75.1 | 75.8 | not run |
| KV cache use (max %) | 0.0 | 0.0 | 0.0 | 0.0 | not run |
| Preemptions | 0 | 0 | 0 | 0 | not run |
| Length finishes | 0 | 0 | 0 | 0 | not run |

## Figure

![SAND-042 1l4-c16 cell dashboard](../figures/1l4-c16-dashboard.png)

## Cost (computed from the session)

Fleet window not recorded (no fleet_window.json for this cell). Per-run costs still come from each run's own container-telemetry window.

## Per-run cards

| Specialist | Run ID | Card |
| --- | --- | --- |
| Correspondence | `sand42-50-correspondence-specialist-awq-1l4-c16` | [sand42-50-correspondence-specialist-awq-1l4-c16.card.md](correspondence/sand42-50-correspondence-specialist-awq-1l4-c16.card.md) |
| Insurance Claims | `sand42-50-insurance-claims-specialist-awq-1l4-c16` | [sand42-50-insurance-claims-specialist-awq-1l4-c16.card.md](insurance_claims/sand42-50-insurance-claims-specialist-awq-1l4-c16.card.md) |
| Corporate Records | `sand42-50-corporate-records-specialist-awq-1l4-c16` | [sand42-50-corporate-records-specialist-awq-1l4-c16.card.md](corporate_records/sand42-50-corporate-records-specialist-awq-1l4-c16.card.md) |
| Contracts | `sand42-50-contracts-specialist-awq-1l4-c16` | [sand42-50-contracts-specialist-awq-1l4-c16.card.md](contracts/sand42-50-contracts-specialist-awq-1l4-c16.card.md) |
| Merger Agreements | `sand42-50-merger-specialist-awq-1l4-c16` | not run |

_Merger dominates pooled throughput (≈ 112k prompt tokens per agreement on the frozen settings), so no pooled column is reported here — compare per class._

_Generated 2026-10-12T06:10:34+00:00 by `sandbox run card --runbook sand42-1l4-c16` from the committed per-run `*.card.json`._
