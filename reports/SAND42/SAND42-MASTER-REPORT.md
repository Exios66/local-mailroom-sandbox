# SAND-042 master report — full detail

Per-condition tables, engine and GPU telemetry, the paired comparison and the method. Executive summary: [`SAND42-MASTER-SCORE-COST-CARD.md`](SAND42-MASTER-SCORE-COST-CARD.md).

# SAND-042 · 1× L4 · client concurrency 8 · n=50 × 5 specialists

**Cells reported:** 5 of 5 · **Runbook:** `sand42-1l4-c8` · **Model:** Qwen/Qwen3-8B-AWQ · L4 @ $0.80/GPU-hr

## Shared conditions

| Condition | Value |
| --- | --- |
| Engine | — · max_model_len 32768 · max_num_seqs 16/replica · max_inputs 32 |
| Fleet | 1 replica(s) · client concurrency 8 (8 per replica) |
| Dataset | `Lucius-Morningstar/mailroom-dataset` ground_truth @ ed7576b6, split=all, seed 42, one class bucket, 50 per class stratified over every subclass (min 1 per sub-type) |
| Prompt | v1 `*_simplified` stems only |
| Output cap | max_tokens 8,192 · temperature 0.7 contracts + merger, 0.1 elsewhere |
| GPU telemetry | in-container nvidia-smi series, label `sand42-1l4-c8` |

## Per specialist

| Metric | Correspondence | Insurance Claims | Corporate Records | Contracts | Merger Agreements |
| --- | ---: | ---: | ---: | ---: | ---: |
| Quality (95% CI) | 0.384 [0.316, 0.451] | 0.670 [0.653, 0.685] | 0.497 [0.427, 0.569] | 0.579 [0.543, 0.614] | 0.021 [0.012, 0.030] |
| Scored documents | 50 | 50 | 50 | 45 | 50 |
| Quality SD | 0.246 | 0.060 | 0.254 | 0.123 | 0.032 |
| Scoring method | suite | suite | suite | suite+cuad | suite+maud |
| Clause metric | — | — | — | CUAD F1 0.585 · 45 labeled | MAUD acc 2.1% · 254/811 answered |
| Ok rate (Wilson) | 50/50 100.0% [0.929, 1.000] | 50/50 100.0% [0.929, 1.000] | 50/50 100.0% [0.929, 1.000] | 50/50 100.0% [0.929, 1.000] | 50/50 100.0% [0.929, 1.000] |
| Schema-valid rate | 100.0% | 30.0% | 96.0% | 100.0% | 100.0% |
| Parse errors | 0 | 0 | 0 | 0 | 0 |
| Length-capped | 0 | 0 | 0 | 0 | 0 |
| Error kinds | — | — | — | — | — |
| p50 latency (s) | 6.3 | 13.6 | 11.2 | 94.5 | 574.9 |
| p95 latency (s) | 8.9 | 24.6 | 13.6 | 316.4 | 1,324.9 |
| SLO (s) · met | 60 · yes | 60 · yes | 60 · yes | 300 · no | 1,800 · yes |
| Documents/min | 49.41 | 23.14 | 34.64 | 3.26 | 0.64 |
| Documents/min/GPU | 49.41 | 23.14 | 34.64 | 3.26 | 0.64 |
| Goodput docs/min/GPU | 49.41 | 23.14 | 34.64 | 0.00 | 0.64 |
| Tokens/s/GPU | 2,258.4 | 1,438.9 | 2,371.5 | 1,009.7 | 1,113.2 |
| Mean TTFT (s) | 0.72 | 0.90 | 1.21 | 1.95 | 4.01 |
| Prefix-cache hit | 63.6% | 58.4% | 50.9% | 38.3% | 18.4% |
| Wall (s) | 60.7 | 129.7 | 86.6 | 920.0 | 4,657.5 |
| Billed GPU $ (run) | $0.0133 | $0.0287 | $0.0194 | $0.2046 | $1.0356 |
| $ / 1k ok docs | $0.266880 | $0.574880 | $0.387920 | $4.091500 | $20.712260 |
| $ / 1k schema-valid | $0.266880 | $1.916267 | $0.404083 | $4.091500 | $20.712260 |
| $ / doc | $0.000267 | $0.000575 | $0.000388 | $0.004092 | $0.020712 |
| $ / ok doc | $0.000267 | $0.000575 | $0.000388 | $0.004092 | $0.020712 |
| $ / 1M tokens | $0.097 | $0.154 | $0.094 | $0.220 | $0.200 |
| GPU util (mean/p95/min–max) | 73.8% mean / 99.0 p95 / 0.0–99.0% min–max (n=8) | 92.8% mean / 99.0 p95 / 0.0–99.0% min–max (n=18) | 77.6% mean / 100.0 p95 / 0.0–100.0% min–max (n=14) | 97.6% mean / 100.0 p95 / 0.0–100.0% min–max (n=139) | 98.3% mean / 100.0 p95 / 0.0–100.0% min–max (n=699) |
| GPU mem used (mean) | 20,994 MiB (91.1% of 23,034) | 21,023 MiB (91.3% of 23,034) | 21,023 MiB (91.3% of 23,034) | 21,026 MiB (91.3% of 23,034) | 21,027 MiB (91.3% of 23,034) |
| GPU mem bandwidth (mean) | not captured — scraped before the sampler read utilization.memory; needs a re-run | not captured — scraped before the sampler read utilization.memory; needs a re-run | not captured — scraped before the sampler read utilization.memory; needs a re-run | not captured — scraped before the sampler read utilization.memory; needs a re-run | not captured — scraped before the sampler read utilization.memory; needs a re-run |
| Sampling coverage | 96.6% | 94.8% | 100.0% | 100.0% | 100.0% |
| GPU power (W, mean) | 63.3 | 69.4 | 63.4 | 71.4 | 71.7 |
| GPU temp (C, mean) | 51.6 | 60.3 | 64.4 | 73.0 | 75.6 |
| KV cache use (%) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) |
| KV cache use, mid-run (max %) | — | — | — | — | — |
| Queue depth, mid-run (running/waiting) | — | — | — | — | — |
| Preemptions | 0 | 0 | 0 | 0 | 0 |
| Length finishes | 0 | 0 | 0 | 0 | 9 |

## Cost (computed from the session)

Fleet window not recorded (no fleet_window.json for this cell). Per-run costs still come from each run's own container-telemetry window.

## Per-run cards

| Specialist | Run ID | Card |
| --- | --- | --- |
| Correspondence | `sand42-50-correspondence-specialist-awq-1l4-c8` | [sand42-50-correspondence-specialist-awq-1l4-c8.card.md](1L4-c8/correspondence/sand42-50-correspondence-specialist-awq-1l4-c8.card.md) |
| Insurance Claims | `sand42-50-insurance-claims-specialist-awq-1l4-c8` | [sand42-50-insurance-claims-specialist-awq-1l4-c8.card.md](1L4-c8/insurance_claims/sand42-50-insurance-claims-specialist-awq-1l4-c8.card.md) |
| Corporate Records | `sand42-50-corporate-records-specialist-awq-1l4-c8` | [sand42-50-corporate-records-specialist-awq-1l4-c8.card.md](1L4-c8/corporate_records/sand42-50-corporate-records-specialist-awq-1l4-c8.card.md) |
| Contracts | `sand42-50-contracts-specialist-awq-1l4-c8` | [sand42-50-contracts-specialist-awq-1l4-c8.card.md](1L4-c8/contracts/sand42-50-contracts-specialist-awq-1l4-c8.card.md) |
| Merger Agreements | `sand42-50-merger-specialist-awq-1l4-c8` | [sand42-50-merger-specialist-awq-1l4-c8.card.md](1L4-c8/merger_agreement/sand42-50-merger-specialist-awq-1l4-c8.card.md) |

_Merger dominates pooled throughput (≈ 112k prompt tokens per agreement on the frozen settings), so no pooled column is reported here — compare per class._

_Generated 2026-10-12T17:48:56+00:00 by `sandbox run card --runbook sand42-1l4-c8` from the committed per-run `*.card.json`._


---

# SAND-042 · 1× L4 · client concurrency 16 · n=50 × 5 specialists

**Cells reported:** 5 of 5 · **Runbook:** `sand42-1l4-c16` · **Model:** Qwen/Qwen3-8B-AWQ · L4 @ $0.80/GPU-hr

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
| Quality (95% CI) | 0.381 [0.313, 0.447] | 0.665 [0.647, 0.683] | 0.484 [0.413, 0.553] | 0.603 [0.565, 0.642] | 0.029 [0.019, 0.039] |
| Scored documents | 50 | 50 | 50 | 45 | 50 |
| Quality SD | 0.244 | 0.063 | 0.251 | 0.130 | 0.036 |
| Scoring method | suite | suite | suite | suite+cuad | suite+maud |
| Clause metric | — | — | — | CUAD F1 0.613 · 45 labeled | MAUD acc 2.8% · 247/811 answered |
| Ok rate (Wilson) | 50/50 100.0% [0.929, 1.000] | 50/50 100.0% [0.929, 1.000] | 50/50 100.0% [0.929, 1.000] | 50/50 100.0% [0.929, 1.000] | 50/50 100.0% [0.929, 1.000] |
| Schema-valid rate | 100.0% | 28.0% | 96.0% | 100.0% | 100.0% |
| Parse errors | 0 | 0 | 0 | 0 | 0 |
| Length-capped | 0 | 0 | 0 | 0 | 0 |
| Error kinds | — | — | — | — | — |
| p50 latency (s) | 9.4 | 20.5 | 19.6 | 176.2 | 1,045.6 |
| p95 latency (s) | 14.0 | 30.3 | 24.3 | 914.4 | 1,891.2 |
| SLO (s) · met | 60 · yes | 60 · yes | 60 · yes | 300 · no | 1,800 · no |
| Documents/min | 63.47 | 28.41 | 39.67 | 2.67 | 0.73 |
| Documents/min/GPU | 63.47 | 28.41 | 39.67 | 2.67 | 0.73 |
| Goodput docs/min/GPU | 63.47 | 28.41 | 39.67 | 0.00 | 0.00 |
| Tokens/s/GPU | 2,905.2 | 1,762.0 | 2,714.7 | 828.7 | 1,262.0 |
| Mean TTFT (s) | 1.42 | 1.80 | 2.56 | 14.35 | 6.71 |
| Prefix-cache hit | 63.6% | 58.4% | 50.9% | 28.1% | 14.0% |
| Wall (s) | 47.3 | 105.6 | 75.6 | 1,124.4 | 4,098.5 |
| Billed GPU $ (run) | $0.0140 | $0.0268 | $0.0206 | $0.2541 | $0.9110 |
| $ / 1k ok docs | $0.279800 | $0.536440 | $0.412340 | $5.082960 | $18.219480 |
| $ / 1k schema-valid | $0.279800 | $1.915857 | $0.429521 | $5.082960 | $18.219480 |
| $ / doc | $0.000280 | $0.000536 | $0.000412 | $0.005083 | $0.018219 |
| $ / ok doc | $0.000280 | $0.000536 | $0.000412 | $0.005083 | $0.018219 |
| $ / 1M tokens | $0.102 | $0.144 | $0.100 | $0.273 | $0.176 |
| GPU util (mean/p95/min–max) | 44.4% mean / 100.0 p95 / 0.0–100.0% min–max (n=11) | 74.6% mean / 100.0 p95 / 0.0–100.0% min–max (n=21) | 67.8% mean / 100.0 p95 / 0.0–100.0% min–max (n=16) | 94.5% mean / 100.0 p95 / 0.0–100.0% min–max (n=167) | 98.2% mean / 100.0 p95 / 0.0–100.0% min–max (n=651) |
| GPU mem used (mean) | 21,002 MiB (91.2% of 23,034) | 21,025 MiB (91.3% of 23,034) | 21,026 MiB (91.3% of 23,034) | 21,024 MiB (91.3% of 23,034) | 21,027 MiB (91.3% of 23,034) |
| GPU mem bandwidth (mean) | 38.9% mean | 66.9% mean | 47.2% mean | 84.7% mean | 78.2% mean |
| Sampling coverage | 100.0% | 100.0% | 100.0% | 88.4% ⚠ below the 90% gate (issue #128) | 100.0% |
| GPU power (W, mean) | 51.0 | 61.7 | 59.2 | 70.5 | 71.7 |
| GPU temp (C, mean) | 73.6 | 75.2 | 75.1 | 75.8 | 76.5 |
| KV cache use (%) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) |
| KV cache use, mid-run (max %) | — | — | — | — | — |
| Queue depth, mid-run (running/waiting) | — | — | — | — | — |
| Preemptions | 0 | 0 | 0 | 0 | 0 |
| Length finishes | 0 | 0 | 0 | 0 | 10 |

## Cost (computed from the session)

The fleet is pinned warm (`min_containers=1`) from deploy to teardown, so Modal meters the **whole window** — the cold boot and the idle between specialists included. This is computed from the session's own timestamps, not scraped from the billing CLI (whose figures are credits-based and workspace-wide).

| Fleet cost | Value |
| --- | ---: |
| Replicas × GPU | 1 × L4 @ $0.80/GPU-hr |
| Cold boot (deploy → ready) | not captured — ready_ts is only written by the parallel-fleet launcher |
| Fleet window (deploy → teardown) | 5,690.0 s |
| Fleet GPU-hours | 1.5806 |
| **Fleet GPU $** | **$1.2644** |
| Of which the five runs | 5,519.5 s (97.0%) |
| Boot + idle overhead | 170.5 s |

## Per-run cards

| Specialist | Run ID | Card |
| --- | --- | --- |
| Correspondence | `sand42-50-correspondence-specialist-awq-1l4-c16` | [sand42-50-correspondence-specialist-awq-1l4-c16.card.md](1L4-c16/correspondence/sand42-50-correspondence-specialist-awq-1l4-c16.card.md) |
| Insurance Claims | `sand42-50-insurance-claims-specialist-awq-1l4-c16` | [sand42-50-insurance-claims-specialist-awq-1l4-c16.card.md](1L4-c16/insurance_claims/sand42-50-insurance-claims-specialist-awq-1l4-c16.card.md) |
| Corporate Records | `sand42-50-corporate-records-specialist-awq-1l4-c16` | [sand42-50-corporate-records-specialist-awq-1l4-c16.card.md](1L4-c16/corporate_records/sand42-50-corporate-records-specialist-awq-1l4-c16.card.md) |
| Contracts | `sand42-50-contracts-specialist-awq-1l4-c16` | [sand42-50-contracts-specialist-awq-1l4-c16.card.md](1L4-c16/contracts/sand42-50-contracts-specialist-awq-1l4-c16.card.md) |
| Merger Agreements | `sand42-50-merger-specialist-awq-1l4-c16` | [sand42-50-merger-specialist-awq-1l4-c16.card.md](1L4-c16/merger_agreement/sand42-50-merger-specialist-awq-1l4-c16.card.md) |

_Merger dominates pooled throughput (≈ 112k prompt tokens per agreement on the frozen settings), so no pooled column is reported here — compare per class._

_Generated 2026-10-12T17:48:57+00:00 by `sandbox run card --runbook sand42-1l4-c16` from the committed per-run `*.card.json`._


---

# SAND-042 · 2× L4 · client concurrency 8 (4 per replica) · n=50 × 5 specialists

**Cells reported:** 5 of 5 · **Runbook:** `sand42-2l4-c8` · **Model:** Qwen/Qwen3-8B-AWQ · L4 @ $0.80/GPU-hr

## Shared conditions

| Condition | Value |
| --- | --- |
| Engine | — · max_model_len 32768 · max_num_seqs 16/replica · max_inputs 32 |
| Fleet | 2 replica(s) · client concurrency 8 (4 per replica) |
| Dataset | `Lucius-Morningstar/mailroom-dataset` ground_truth @ ed7576b6, split=all, seed 42, one class bucket, 50 per class stratified over every subclass (min 1 per sub-type) |
| Prompt | v1 `*_simplified` stems only |
| Output cap | max_tokens 8,192 · temperature 0.7 contracts + merger, 0.1 elsewhere |
| GPU telemetry | in-container nvidia-smi series, label `sand42-2l4-c8` |

## Per specialist

| Metric | Correspondence | Insurance Claims | Corporate Records | Contracts | Merger Agreements |
| --- | ---: | ---: | ---: | ---: | ---: |
| Quality (95% CI) | 0.379 [0.310, 0.447] | 0.670 [0.653, 0.687] | 0.481 [0.412, 0.550] | 0.622 [0.581, 0.659] | 0.031 [0.020, 0.043] |
| Scored documents | 50 | 50 | 50 | 44 | 50 |
| Quality SD | 0.241 | 0.064 | 0.249 | 0.131 | 0.042 |
| Scoring method | suite | suite | suite | suite+cuad | suite+maud |
| Clause metric | — | — | — | CUAD F1 0.615 · 44 labeled | MAUD acc 3.1% · 283/811 answered |
| Ok rate (Wilson) | 50/50 100.0% [0.929, 1.000] | 50/50 100.0% [0.929, 1.000] | 50/50 100.0% [0.929, 1.000] | 49/50 98.0% [0.895, 0.996] | 50/50 100.0% [0.929, 1.000] |
| Schema-valid rate | 100.0% | 30.0% | 96.0% | 100.0% | 100.0% |
| Parse errors | 0 | 0 | 0 | 0 | 0 |
| Length-capped | 0 | 0 | 0 | 1 | 0 |
| Error kinds | — | — | — | LengthFinishReasonError×1 | — |
| p50 latency (s) | 5.4 | 11.4 | 7.7 | 76.5 | 389.7 |
| p95 latency (s) | 8.1 | 18.6 | 11.5 | 293.0 | 891.4 |
| SLO (s) · met | 60 · yes | 60 · yes | 60 · yes | 300 · yes | 1,800 · yes |
| Documents/min | 59.25 | 25.06 | 46.21 | 3.06 | 0.94 |
| Documents/min/GPU | 29.63 | 12.53 | 23.10 | 1.53 | 0.47 |
| Goodput docs/min/GPU | 29.63 | 12.53 | 23.10 | 1.53 | 0.47 |
| Tokens/s/GPU | 1,356.4 | 777.6 | 1,581.2 | 445.6 | 811.3 |
| Mean TTFT (s) | 0.60 | 0.68 | 0.86 | 1.57 | 3.25 |
| Prefix-cache hit | 62.2% | 57.2% | 49.9% | 37.7% | 17.9% |
| Wall (s) | 50.6 | 119.7 | 64.9 | 981.5 | 3,186.0 |
| Billed GPU $ (run) | $0.0231 | $0.0536 | $0.0294 | $0.4367 | $1.4163 |
| $ / 1k ok docs | $0.461040 | $1.072720 | $0.588180 | $8.912980 | $28.326080 |
| $ / 1k schema-valid | $0.461040 | $3.575733 | $0.612688 | $8.734720 | $28.326080 |
| $ / doc | $0.000461 | $0.001073 | $0.000588 | $0.008735 | $0.028326 |
| $ / ok doc | $0.000461 | $0.001073 | $0.000588 | $0.008913 | $0.028326 |
| $ / 1M tokens | $0.168 | $0.288 | $0.143 | $0.499 | $0.274 |
| GPU util (mean/p95/min–max) | 69.1% mean / 100.0 p95 / 0.0–100.0% min–max (n=17) | 75.3% mean / 100.0 p95 / 0.0–100.0% min–max (n=40) | 79.6% mean / 100.0 p95 / 0.0–100.0% min–max (n=21) | 84.2% mean / 100.0 p95 / 0.0–100.0% min–max (n=333) | 80.6% mean / 100.0 p95 / 0.0–100.0% min–max (n=1071) |
| GPU mem used (mean) | 20,983 MiB (91.1% of 23,034) | 20,997 MiB (91.2% of 23,034) | 20,997 MiB (91.2% of 23,034) | 21,000 MiB (91.2% of 23,034) | 21,002 MiB (91.2% of 23,034) |
| GPU mem bandwidth (mean) | 56.4% mean | 73.0% mean | 64.5% mean | 80.0% mean | 68.5% mean |
| Sampling coverage | 100.0% | 100.0% | 100.0% | 99.1% | 99.7% |
| GPU power (W, mean) | 61.7 | 63.0 | 62.8 | 66.8 | 64.9 |
| GPU temp (C, mean) | 71.6 | 75.8 | 77.0 | 76.0 | 75.5 |
| KV cache use (%) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) |
| KV cache use, mid-run (max %) | — | — | — | — | — |
| Queue depth, mid-run (running/waiting) | — | — | — | — | — |
| Preemptions | 0 | 0 | 0 | 0 | 0 |
| Length finishes | 0 | 0 | 0 | 4 | 8 |

## Cost (computed from the session)

The fleet is pinned warm (`min_containers=1`) from deploy to teardown, so Modal meters the **whole window** — the cold boot and the idle between specialists included. This is computed from the session's own timestamps, not scraped from the billing CLI (whose figures are credits-based and workspace-wide).

| Fleet cost | Value |
| --- | ---: |
| Replicas × GPU | 2 × L4 @ $0.80/GPU-hr |
| Cold boot (deploy → ready) | not captured — ready_ts is only written by the parallel-fleet launcher |
| Fleet window (deploy → teardown) | 4,750.0 s |
| Fleet GPU-hours | 2.6389 |
| **Fleet GPU $** | **$2.1111** |
| Of which the five runs | 4,408.1 s (92.8%) |
| Boot + idle overhead | 341.9 s |

## Per-run cards

| Specialist | Run ID | Card |
| --- | --- | --- |
| Correspondence | `sand42-50-correspondence-specialist-awq-2l4-c8` | [sand42-50-correspondence-specialist-awq-2l4-c8.card.md](2L4-c8/correspondence/sand42-50-correspondence-specialist-awq-2l4-c8.card.md) |
| Insurance Claims | `sand42-50-insurance-claims-specialist-awq-2l4-c8` | [sand42-50-insurance-claims-specialist-awq-2l4-c8.card.md](2L4-c8/insurance_claims/sand42-50-insurance-claims-specialist-awq-2l4-c8.card.md) |
| Corporate Records | `sand42-50-corporate-records-specialist-awq-2l4-c8` | [sand42-50-corporate-records-specialist-awq-2l4-c8.card.md](2L4-c8/corporate_records/sand42-50-corporate-records-specialist-awq-2l4-c8.card.md) |
| Contracts | `sand42-50-contracts-specialist-awq-2l4-c8` | [sand42-50-contracts-specialist-awq-2l4-c8.card.md](2L4-c8/contracts/sand42-50-contracts-specialist-awq-2l4-c8.card.md) |
| Merger Agreements | `sand42-50-merger-specialist-awq-2l4-c8` | [sand42-50-merger-specialist-awq-2l4-c8.card.md](2L4-c8/merger_agreement/sand42-50-merger-specialist-awq-2l4-c8.card.md) |

_Merger dominates pooled throughput (≈ 112k prompt tokens per agreement on the frozen settings), so no pooled column is reported here — compare per class._

_Generated 2026-10-12T17:48:57+00:00 by `sandbox run card --runbook sand42-2l4-c8` from the committed per-run `*.card.json`._


---

# SAND-042 · 2× L4 · client concurrency 16 (8 per replica) · n=50 × 5 specialists

**Cells reported:** 5 of 5 · **Runbook:** `sand42-2l4-c16` · **Model:** Qwen/Qwen3-8B-AWQ · L4 @ $0.80/GPU-hr

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
| Quality (95% CI) | 0.382 [0.318, 0.447] | 0.668 [0.650, 0.686] | 0.498 [0.430, 0.565] | 0.606 [0.569, 0.642] | 0.024 [0.015, 0.033] |
| Scored documents | 50 | 50 | 50 | 44 | 50 |
| Quality SD | 0.237 | 0.063 | 0.247 | 0.126 | 0.033 |
| Scoring method | suite | suite | suite | suite+cuad | suite+maud |
| Clause metric | — | — | — | CUAD F1 0.604 · 44 labeled | MAUD acc 2.3% · 349/811 answered |
| Ok rate (Wilson) | 50/50 100.0% [0.929, 1.000] | 50/50 100.0% [0.929, 1.000] | 50/50 100.0% [0.929, 1.000] | 49/50 98.0% [0.895, 0.996] | 50/50 100.0% [0.929, 1.000] |
| Schema-valid rate | 100.0% | 24.0% | 98.0% | 100.0% | 100.0% |
| Parse errors | 0 | 0 | 0 | 0 | 0 |
| Length-capped | 0 | 0 | 0 | 1 | 0 |
| Error kinds | — | — | — | LengthFinishReasonError×1 | — |
| p50 latency (s) | 6.7 | 14.4 | 11.2 | 104.8 | 605.1 |
| p95 latency (s) | 10.8 | 22.5 | 19.1 | 431.5 | 1,742.0 |
| SLO (s) · met | 60 · yes | 60 · yes | 60 · yes | 300 · no | 1,800 · yes |
| Documents/min | 75.20 | 34.89 | 55.86 | 2.82 | 1.05 |
| Documents/min/GPU | 37.60 | 17.44 | 27.93 | 1.41 | 0.52 |
| Goodput docs/min/GPU | 37.60 | 17.44 | 27.93 | 0.00 | 0.52 |
| Tokens/s/GPU | 1,719.0 | 1,078.8 | 1,914.0 | 422.3 | 901.3 |
| Mean TTFT (s) | 1.04 | 1.33 | 1.55 | 2.51 | 3.93 |
| Prefix-cache hit | 62.5% | 57.2% | 49.9% | 37.7% | 18.8% |
| Wall (s) | 39.9 | 86.0 | 53.7 | 1,063.4 | 2,866.6 |
| Billed GPU $ (run) | $0.0180 | $0.0385 | $0.0241 | $0.4730 | $1.2749 |
| $ / 1k ok docs | $0.359540 | $0.769340 | $0.481800 | $9.653776 | $25.497100 |
| $ / 1k schema-valid | $0.359540 | $3.205583 | $0.491633 | $9.460700 | $25.497100 |
| $ / doc | $0.000360 | $0.000769 | $0.000482 | $0.009461 | $0.025497 |
| $ / ok doc | $0.000360 | $0.000769 | $0.000482 | $0.009654 | $0.025497 |
| $ / 1M tokens | $0.131 | $0.207 | $0.117 | $0.527 | $0.247 |
| GPU util (mean/p95/min–max) | 63.7% mean / 98.0 p95 / 0.0–100.0% min–max (n=12) | 76.3% mean / 100.0 p95 / 0.0–100.0% min–max (n=27) | 65.4% mean / 100.0 p95 / 0.0–100.0% min–max (n=18) | 79.9% mean / 100.0 p95 / 0.0–100.0% min–max (n=359) | 82.2% mean / 100.0 p95 / 0.0–100.0% min–max (n=962) |
| GPU mem used (mean) | 19,973 MiB (86.7% of 23,034) | 19,993 MiB (86.8% of 23,034) | 19,994 MiB (86.8% of 23,034) | 19,994 MiB (86.8% of 23,034) | 19,996 MiB (86.8% of 23,034) |
| GPU mem bandwidth (mean) | 57.8% mean | 69.0% mean | 52.3% mean | 76.8% mean | 69.0% mean |
| Sampling coverage | 95.6% | 100.0% | 65.6% ⚠ below the 90% gate (issue #128) | 99.4% | 99.6% |
| GPU power (W, mean) | 56.8 | 62.9 | 59.8 | 64.6 | 65.7 |
| GPU temp (C, mean) | 62.3 | 69.8 | 74.4 | 73.5 | 75.5 |
| KV cache use (%) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) |
| KV cache use, mid-run (max %) | — | — | — | — | — |
| Queue depth, mid-run (running/waiting) | — | — | — | — | — |
| Preemptions | 0 | 0 | 0 | 0 | 0 |
| Length finishes | 0 | 0 | 0 | 4 | 12 |

## Cost (computed from the session)

The fleet is pinned warm (`min_containers=1`) from deploy to teardown, so Modal meters the **whole window** — the cold boot and the idle between specialists included. This is computed from the session's own timestamps, not scraped from the billing CLI (whose figures are credits-based and workspace-wide).

| Fleet cost | Value |
| --- | ---: |
| Replicas × GPU | 2 × L4 @ $0.80/GPU-hr |
| Cold boot (deploy → ready) | 292.0 s |
| Fleet window (deploy → teardown) | 4,507.0 s |
| Fleet GPU-hours | 2.5039 |
| **Fleet GPU $** | **$2.0031** |
| Of which the five runs | 4,114.0 s (91.3%) |
| Boot + idle overhead | 393.0 s |

## Per-run cards

| Specialist | Run ID | Card |
| --- | --- | --- |
| Correspondence | `sand42-50-correspondence-specialist-awq-2l4-c16` | [sand42-50-correspondence-specialist-awq-2l4-c16.card.md](2L4-c16/correspondence/sand42-50-correspondence-specialist-awq-2l4-c16.card.md) |
| Insurance Claims | `sand42-50-insurance-claims-specialist-awq-2l4-c16` | [sand42-50-insurance-claims-specialist-awq-2l4-c16.card.md](2L4-c16/insurance_claims/sand42-50-insurance-claims-specialist-awq-2l4-c16.card.md) |
| Corporate Records | `sand42-50-corporate-records-specialist-awq-2l4-c16` | [sand42-50-corporate-records-specialist-awq-2l4-c16.card.md](2L4-c16/corporate_records/sand42-50-corporate-records-specialist-awq-2l4-c16.card.md) |
| Contracts | `sand42-50-contracts-specialist-awq-2l4-c16` | [sand42-50-contracts-specialist-awq-2l4-c16.card.md](2L4-c16/contracts/sand42-50-contracts-specialist-awq-2l4-c16.card.md) |
| Merger Agreements | `sand42-50-merger-specialist-awq-2l4-c16` | [sand42-50-merger-specialist-awq-2l4-c16.card.md](2L4-c16/merger_agreement/sand42-50-merger-specialist-awq-2l4-c16.card.md) |

_Merger dominates pooled throughput (≈ 112k prompt tokens per agreement on the frozen settings), so no pooled column is reported here — compare per class._

_Generated 2026-10-12T17:48:57+00:00 by `sandbox run card --runbook sand42-2l4-c16` from the committed per-run `*.card.json`._


---

# SAND-042 · 2× L4 · client concurrency 32 (16 per replica) · n=50 × 5 specialists

**Cells reported:** 5 of 5 · **Runbook:** `sand42-2l4-c32` · **Model:** Qwen/Qwen3-8B-AWQ · L4 @ $0.80/GPU-hr

## Shared conditions

| Condition | Value |
| --- | --- |
| Engine | — · max_model_len 32768 · max_num_seqs 16/replica · max_inputs 32 |
| Fleet | 2 replica(s) · client concurrency 32 (16 per replica) |
| Dataset | `Lucius-Morningstar/mailroom-dataset` ground_truth @ ed7576b6, split=all, seed 42, one class bucket, 50 per class stratified over every subclass (min 1 per sub-type) |
| Prompt | v1 `*_simplified` stems only |
| Output cap | max_tokens 8,192 · temperature 0.7 contracts + merger, 0.1 elsewhere |
| GPU telemetry | in-container nvidia-smi series, label `sand42-2l4-c32` |

## Per specialist

| Metric | Correspondence | Insurance Claims | Corporate Records | Contracts | Merger Agreements |
| --- | ---: | ---: | ---: | ---: | ---: |
| Quality (95% CI) | 0.378 [0.312, 0.443] | 0.670 [0.654, 0.688] | 0.485 [0.412, 0.555] | 0.593 [0.555, 0.628] | 0.024 [0.016, 0.032] |
| Scored documents | 50 | 50 | 50 | 45 | 50 |
| Quality SD | 0.236 | 0.062 | 0.253 | 0.126 | 0.030 |
| Scoring method | suite | suite | suite | suite+cuad | suite+maud |
| Clause metric | — | — | — | CUAD F1 0.593 · 45 labeled | MAUD acc 2.5% · 267/811 answered |
| Ok rate (Wilson) | 50/50 100.0% [0.929, 1.000] | 50/50 100.0% [0.929, 1.000] | 50/50 100.0% [0.929, 1.000] | 50/50 100.0% [0.929, 1.000] | 50/50 100.0% [0.929, 1.000] |
| Schema-valid rate | 100.0% | 30.0% | 96.0% | 100.0% | 100.0% |
| Parse errors | 0 | 0 | 0 | 0 | 0 |
| Length-capped | 0 | 0 | 0 | 0 | 0 |
| Error kinds | — | — | — | — | — |
| p50 latency (s) | 12.9 | 28.8 | 19.1 | 172.2 | 987.5 |
| p95 latency (s) | 22.3 | 42.4 | 33.3 | 502.4 | 1,685.6 |
| SLO (s) · met | 60 · yes | 60 · yes | 60 · yes | 300 · no | 1,800 · yes |
| Documents/min | 76.82 | 40.24 | 61.14 | 2.92 | 1.52 |
| Documents/min/GPU | 38.41 | 20.12 | 30.57 | 1.46 | 0.76 |
| Goodput docs/min/GPU | 38.41 | 20.12 | 30.57 | 0.00 | 0.76 |
| Tokens/s/GPU | 1,756.5 | 1,246.4 | 2,091.8 | 436.5 | 1,313.0 |
| Mean TTFT (s) | 3.39 | 4.73 | 5.64 | 11.26 | 23.37 |
| Prefix-cache hit | 61.7% | 55.1% | 48.3% | 37.1% | 16.9% |
| Wall (s) | 39.1 | 74.6 | 49.1 | 1,026.4 | 1,972.3 |
| Billed GPU $ (run) | $0.0176 | $0.0335 | $0.0221 | $0.4563 | $0.8767 |
| $ / 1k ok docs | $0.352680 | $0.669460 | $0.442320 | $9.125560 | $17.534160 |
| $ / 1k schema-valid | $0.352680 | $2.231533 | $0.460750 | $9.125560 | $17.534160 |
| $ / doc | $0.000353 | $0.000669 | $0.000442 | $0.009126 | $0.017534 |
| $ / ok doc | $0.000353 | $0.000669 | $0.000442 | $0.009126 | $0.017534 |
| $ / 1M tokens | $0.129 | $0.180 | $0.108 | $0.509 | $0.169 |
| GPU util (mean/p95/min–max) | 62.3% mean / 100.0 p95 / 0.0–100.0% min–max (n=11) | 75.6% mean / 100.0 p95 / 0.0–100.0% min–max (n=22) | 68.6% mean / 100.0 p95 / 0.0–100.0% min–max (n=13) | 83.1% mean / 100.0 p95 / 0.0–100.0% min–max (n=313) | 94.8% mean / 100.0 p95 / 0.0–100.0% min–max (n=596) |
| GPU mem used (mean) | 20,981 MiB (91.1% of 23,034) | 21,023 MiB (91.3% of 23,034) | 21,023 MiB (91.3% of 23,034) | 21,027 MiB (91.3% of 23,034) | 21,027 MiB (91.3% of 23,034) |
| GPU mem bandwidth (mean) | 54.5% mean | 70.3% mean | 49.4% mean | 79.8% mean | 74.8% mean |
| Sampling coverage | 100.0% | 100.0% | 86.2% ⚠ below the 90% gate (issue #128) | 97.0% | 99.4% |
| GPU power (W, mean) | 57.2 | 64.6 | 60.0 | 66.1 | 70.1 |
| GPU temp (C, mean) | 67.5 | 74.6 | 76.4 | 76.0 | 75.8 |
| KV cache use (%) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) | 0 (drained-edge sample: the scrapes fire before/after the run, when the cache is empty by construction; a mid-run sample is the only real source) |
| KV cache use, mid-run (max %) | — | — | — | — | 99.0% |
| Queue depth, mid-run (running/waiting) | — | — | — | — | 16 running / 10 waiting |
| Preemptions | 0 | 0 | 0 | 0 | 0 |
| Length finishes | 0 | 0 | 0 | 3 | 4 |

## Cost (computed from the session)

The fleet is pinned warm (`min_containers=1`) from deploy to teardown, so Modal meters the **whole window** — the cold boot and the idle between specialists included. This is computed from the session's own timestamps, not scraped from the billing CLI (whose figures are credits-based and workspace-wide).

| Fleet cost | Value |
| --- | ---: |
| Replicas × GPU | 2 × L4 @ $0.80/GPU-hr |
| Cold boot (deploy → ready) | 217.0 s |
| Fleet window (deploy → teardown) | 3,471.0 s |
| Fleet GPU-hours | 1.9283 |
| **Fleet GPU $** | **$1.5427** |
| Of which the five runs | 3,164.0 s (91.2%) |
| Boot + idle overhead | 307.0 s |

## Per-run cards

| Specialist | Run ID | Card |
| --- | --- | --- |
| Correspondence | `sand42-50-correspondence-specialist-awq-2l4-c32` | [sand42-50-correspondence-specialist-awq-2l4-c32.card.md](2L4-c32/correspondence/sand42-50-correspondence-specialist-awq-2l4-c32.card.md) |
| Insurance Claims | `sand42-50-insurance-claims-specialist-awq-2l4-c32` | [sand42-50-insurance-claims-specialist-awq-2l4-c32.card.md](2L4-c32/insurance_claims/sand42-50-insurance-claims-specialist-awq-2l4-c32.card.md) |
| Corporate Records | `sand42-50-corporate-records-specialist-awq-2l4-c32` | [sand42-50-corporate-records-specialist-awq-2l4-c32.card.md](2L4-c32/corporate_records/sand42-50-corporate-records-specialist-awq-2l4-c32.card.md) |
| Contracts | `sand42-50-contracts-specialist-awq-2l4-c32` | [sand42-50-contracts-specialist-awq-2l4-c32.card.md](2L4-c32/contracts/sand42-50-contracts-specialist-awq-2l4-c32.card.md) |
| Merger Agreements | `sand42-50-merger-specialist-awq-2l4-c32` | [sand42-50-merger-specialist-awq-2l4-c32.card.md](2L4-c32/merger_agreement/sand42-50-merger-specialist-awq-2l4-c32.card.md) |

_Merger dominates pooled throughput (≈ 112k prompt tokens per agreement on the frozen settings), so no pooled column is reported here — compare per class._

_Generated 2026-10-12T17:48:57+00:00 by `sandbox run card --runbook sand42-2l4-c32` from the committed per-run `*.card.json`._


---

# SAND-042 · paired comparison across the 5 cells

All 5 cells score the **identical 250 documents** (5 specialists × 50, one subclass-stratified draw), so every cell-to-cell delta below is **paired**: the unit of analysis is the per-document score difference. Intervals are 95% percentile bootstrap over documents; the last column is the paired n that Δ = 0.05 would need at 80% power.

Reference cell: **1l4-c8** (1×L4, client concurrency 8).

## 1l4-c16 (1× L4 · C16) vs 1l4-c8

| Class | Paired n | Δ mean | 95% CI | SD_diff | better / worse / tie | n for Δ=0.05 |
| --- | ---: | ---: | --- | ---: | --- | ---: |
| Contracts | 45 | +0.024 | [-0.006, 0.055] | 0.105 | 24 / 15 / 6 | 35 |
| Corporate Records | 50 | -0.013 | [-0.035, 0.003] | 0.069 | 3 / 3 / 44 | 15 |
| Correspondence | 50 | -0.003 | [-0.022, 0.017] | 0.070 | 2 / 5 / 43 | 16 |
| Insurance Claims | 50 | -0.005 | [-0.013, 0.002] | 0.027 | 11 / 14 / 25 | 3 |
| Merger Agreements | 50 | +0.008 | [-0.002, 0.020] | 0.039 | 9 / 5 / 36 | 5 |

## 2l4-c8 (2× L4 · C8 · 4/replica) vs 1l4-c8

| Class | Paired n | Δ mean | 95% CI | SD_diff | better / worse / tie | n for Δ=0.05 |
| --- | ---: | ---: | --- | ---: | --- | ---: |
| Contracts | 44 | +0.042 | [0.002, 0.081] | 0.134 | 26 / 11 / 7 | 57 |
| Corporate Records | 50 | -0.016 | [-0.038, 0.001] | 0.073 | 2 / 6 / 42 | 17 |
| Correspondence | 50 | -0.005 | [-0.019, 0.005] | 0.045 | 1 / 3 / 46 | 7 |
| Insurance Claims | 50 | +0.001 | [-0.005, 0.007] | 0.023 | 10 / 10 / 30 | 2 |
| Merger Agreements | 50 | +0.010 | [-0.003, 0.025] | 0.048 | 13 / 6 / 31 | 8 |

## 2l4-c16 (2× L4 · C16 · 8/replica) vs 1l4-c8

| Class | Paired n | Δ mean | 95% CI | SD_diff | better / worse / tie | n for Δ=0.05 |
| --- | ---: | ---: | --- | ---: | --- | ---: |
| Contracts | 44 | +0.025 | [-0.012, 0.064] | 0.129 | 20 / 19 / 5 | 53 |
| Corporate Records | 50 | +0.001 | [-0.018, 0.021] | 0.069 | 4 / 4 / 42 | 15 |
| Correspondence | 50 | -0.003 | [-0.029, 0.021] | 0.091 | 3 / 5 / 42 | 27 |
| Insurance Claims | 50 | -0.001 | [-0.007, 0.003] | 0.018 | 14 / 11 / 25 | 2 |
| Merger Agreements | 50 | +0.003 | [-0.008, 0.014] | 0.041 | 9 / 7 / 34 | 6 |

## 2l4-c32 (2× L4 · C32 · 16/replica) vs 1l4-c8

| Class | Paired n | Δ mean | 95% CI | SD_diff | better / worse / tie | n for Δ=0.05 |
| --- | ---: | ---: | --- | ---: | --- | ---: |
| Contracts | 45 | +0.014 | [-0.023, 0.052] | 0.131 | 23 / 14 / 8 | 55 |
| Corporate Records | 50 | -0.012 | [-0.033, 0.003] | 0.067 | 1 / 3 / 46 | 15 |
| Correspondence | 50 | -0.007 | [-0.019, 0.000] | 0.040 | 0 / 3 / 47 | 5 |
| Insurance Claims | 50 | +0.001 | [-0.005, 0.006] | 0.019 | 11 / 9 / 30 | 2 |
| Merger Agreements | 50 | +0.003 | [-0.006, 0.012] | 0.033 | 8 / 4 / 38 | 4 |

## Noise floor (run-to-run, same 50 documents)

_Not measured._ Run `sand42-noise-floor` (blocked until spend is approved) on the same 50 correspondence documents. Until then the SAND-037/39 floor in `docs/BENCHMARK-PROGRAM.md` §3 is the prior — it was measured on a different draw, so treat it as indicative only.

## Why a paired n can be below the class's document count

The unit of analysis is the **per-document** score difference, so a class's paired n is the intersection of the documents both arms score. Where that is less than the 50-document draw, this is why:

* `contracts_specialist` — the paired n is capped at **45 of 50** documents: its task-native metric (`cuad`) is defined only for the 45 contracts that carry ground truth for it. The remainder ran successfully (`ok` true, no error) but score no numeric value in ANY arm, so they can never enter a paired delta. The cap is a property of the ground truth, not of these runs.
* `contracts_specialist` / `2l4-c8` — scores 44 of the 45 available documents; the shortfall is this arm's own failure (LengthFinishReasonError ×1), so its paired n against `1l4-c8` is the intersection.
* `contracts_specialist` / `2l4-c16` — scores 44 of the 45 available documents; the shortfall is this arm's own failure (LengthFinishReasonError ×1), so its paired n against `1l4-c8` is the intersection.

_Generated 2026-10-12T17:48:59+00:00 by `sandbox run card --runbook sand42`._


---

## Figures

![Quality](figures/cmp-quality.png)
![Cost](figures/cmp-cost.png)
![Latency](figures/cmp-latency.png)
![Throughput](figures/cmp-throughput.png)
![Gpu](figures/cmp-gpu.png)

---

## Method

* Engine, prompts, decode, dataset pin and draw are identical across the 5 conditions; only the replica count and the client concurrency differ (asserted in `tests/test_sand42_grid.py`).
* Client concurrency is split equally across replicas: 2×L4 C8 → 4 per replica, 2×L4 C16 → 8 per replica, 2×L4 C32 → 16 per replica (the engine's `max_num_seqs` ceiling).
* One warm fleet per condition (`min_containers = max_containers = replicas`), five specialists chained, teardown after the fifth: one cold boot per condition.
* Quality intervals are percentile bootstraps over per-document scores; deltas are paired on the shared 250 documents; ok rates use a Wilson interval.
* GPU hardware telemetry is sampled inside the serving replica (nvidia-smi util / power / temperature / memory) and recorded per condition; vLLM `/metrics` gives the engine side (TTFT, prefix-cache hit rate, preemptions, length finishes, KV use) per replica.
* Sample sizes, the noise floor and the contracts caveat: `docs/BENCHMARK-PROGRAM.md` §3 and `docs/SAND42-EXPERIMENT-DESIGN.md` §4.

## Metric completeness

Measured from the artifacts rather than asserted — `verbatim /metrics` is the full
exporter output preserved per replica; `bandwidth` is the in-container nvidia-smi
series carrying `utilization.memory`; `mid-run KV` is a sample taken while the run was
WORKING (the before/after scrapes bracket the run and read 0 by construction); `cold
boot` is the fleet window having recorded `ready_ts`.

| Cell | verbatim /metrics | GPU mem bandwidth | mid-run KV / queue | cold boot |
| --- | ---: | ---: | ---: | ---: |
| `1l4-c8` | 1/2 | 1/2 | 1/2 | no |
| `1l4-c16` | 1/5 | all | 0/5 | no |
| `2l4-c8` | all | all | 0/5 | no |
| `2l4-c16` | all | all | 0/5 | yes |
| `2l4-c32` | all | all | 1/5 | yes |

**Open coverage.** Every blank above carries its reason; a gap is never rendered as a number, and none of these blanks is a failed capture:

* `1l4-c8` — verbatim /metrics: 1 of 2 run(s) not sampled
* `1l4-c8` — GPU memory bandwidth: 1 of 2 run(s) not sampled
* `1l4-c8` — mid-run KV / queue: 1 of 2 run(s) not sampled
* `1l4-c8` — cold boot: `ready_ts` never written (the sequential driver's cells record a fleet window without a boot boundary)
* `1l4-c16` — verbatim /metrics: 4 of 5 run(s) not sampled
* `1l4-c16` — mid-run KV / queue: 5 of 5 run(s) not sampled
* `1l4-c16` — cold boot: `ready_ts` never written (the sequential driver's cells record a fleet window without a boot boundary)
* `2l4-c8` — mid-run KV / queue: 5 of 5 run(s) not sampled
* `2l4-c8` — cold boot: `ready_ts` never written (the sequential driver's cells record a fleet window without a boot boundary)
* `2l4-c16` — mid-run KV / queue: 5 of 5 run(s) not sampled
* `2l4-c32` — mid-run KV / queue: 4 of 5 run(s) not sampled

*Mid-run KV / queue is diagnostic telemetry, not a primary endpoint — it explains a throughput result rather than producing one, and no headline number depends on it. The primary endpoints (per-class throughput, $/1k ok documents, quality with CIs) and the verbatim engine telemetry are complete for every cell. Per-class pairing ceilings (e.g. contracts) are explained in the comparison's pairing note.*

## Open items

* The noise-floor leg (`sand42-noise-floor`) runs with the 1L4-C8 re-run (spend approved 2026-10-12), so the deltas above carry this campaign's own run-to-run floor rather than the SAND-037/39 prior, which was measured on a different draw.
* Mid-run KV / queue is unsampled for `2l4-c8` and for four of the five `2l4-c32` runs. Both are re-runnable without changing the design; the completeness table above is generated from the run store, so it cannot go stale when they land.
* Contracts at n=50 paired is marginal for Δ=0.05 and unpowered for Δ=0.03 — report as an interval, never a ranking.
* OTel *metrics* export from the container is not wired (the telemetry is an nvidia-smi series); trace spans stay opt-in via `trace.sink`.
* This grid shows the second L4 does not pay per GPU, but not whether that is a property of the L4s or of the client feeding them. The controlled test — data-parallel with a per-request feed, tensor-parallel on one endpoint, and a raised admission ceiling — is designed in [`docs/SAND42-FOLLOWUP-DESIGN.md`](../../docs/SAND42-FOLLOWUP-DESIGN.md).

_Generated 2026-10-12T17:48:57+00:00 by `sandbox run card --runbook sand42`._
