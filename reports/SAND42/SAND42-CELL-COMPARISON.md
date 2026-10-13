# SAND-042 · paired comparison across the 5 cells

**The cells do NOT all score the same documents.** `sand42-50-contracts`: ['1l4-c16', '1l4-c8', '2l4-c16'] (50 docs) vs ['2l4-c32', '2l4-c8'] (50 docs). Any delta between cells on different draws is **not paired** — the per-document difference is undefined across a draw change, so those columns compare different documents and must not be read as a comparison until every cell re-runs on one draw. Everything else in this table (cost, throughput, engine telemetry) is unaffected.

Reference cell: **1l4-c8** (1×L4, client concurrency 8).

## 1l4-c16 (1× L4 · C16) vs 1l4-c8

| Class | Paired n | Δ mean | 95% CI | SD_diff | better / worse / tie | n for Δ=0.05 |
| --- | ---: | ---: | --- | ---: | --- | ---: |
| Contracts | 50 | +0.005 | [-0.024, 0.038] | 0.111 | 22 / 17 / 11 | 39 |
| Corporate Records | 50 | +0.012 | [-0.000, 0.028] | 0.055 | 5 / 1 / 44 | 10 |
| Correspondence | 50 | -0.009 | [-0.026, 0.001] | 0.051 | 2 / 3 / 45 | 9 |
| Insurance Claims | 50 | -0.004 | [-0.012, 0.003] | 0.028 | 8 / 10 / 32 | 3 |
| Merger Agreements | 50 | +0.000 | [-0.015, 0.015] | 0.054 | 8 / 7 / 35 | 9 |

## 2l4-c8 (2× L4 · C8 · 4/replica) vs 1l4-c8

| Class | Paired n | Δ mean | 95% CI | SD_diff | better / worse / tie | n for Δ=0.05 |
| --- | ---: | ---: | --- | ---: | --- | ---: |
| Contracts | 38 | +0.018 | [-0.023, 0.060] | 0.129 | 18 / 12 / 8 | 53 |
| Corporate Records | 50 | -0.002 | [-0.018, 0.010] | 0.053 | 4 / 3 / 43 | 9 |
| Correspondence | 50 | -0.009 | [-0.025, 0.001] | 0.049 | 1 / 3 / 46 | 8 |
| Insurance Claims | 50 | -0.001 | [-0.005, 0.003] | 0.014 | 7 / 7 / 36 | 1 |
| Merger Agreements | 50 | +0.004 | [-0.006, 0.013] | 0.034 | 8 / 4 / 38 | 4 |

## 2l4-c16 (2× L4 · C16 · 8/replica) vs 1l4-c8

| Class | Paired n | Δ mean | 95% CI | SD_diff | better / worse / tie | n for Δ=0.05 |
| --- | ---: | ---: | --- | ---: | --- | ---: |
| Contracts | 50 | +0.006 | [-0.025, 0.039] | 0.117 | 21 / 20 / 9 | 44 |
| Corporate Records | 50 | +0.006 | [0.000, 0.012] | 0.023 | 5 / 1 / 44 | 2 |
| Correspondence | 50 | +0.002 | [-0.021, 0.026] | 0.086 | 3 / 4 / 43 | 24 |
| Insurance Claims | 50 | -0.001 | [-0.007, 0.004] | 0.019 | 11 / 6 / 33 | 2 |
| Merger Agreements | 50 | -0.002 | [-0.016, 0.011] | 0.047 | 8 / 8 / 34 | 7 |

## 2l4-c32 (2× L4 · C32 · 16/replica) vs 1l4-c8

| Class | Paired n | Δ mean | 95% CI | SD_diff | better / worse / tie | n for Δ=0.05 |
| --- | ---: | ---: | --- | ---: | --- | ---: |
| Contracts | 39 | -0.005 | [-0.046, 0.036] | 0.133 | 16 / 15 / 8 | 56 |
| Corporate Records | 50 | +0.003 | [-0.017, 0.022] | 0.069 | 3 / 1 / 46 | 15 |
| Correspondence | 50 | -0.010 | [-0.028, 0.001] | 0.053 | 2 / 5 / 43 | 9 |
| Insurance Claims | 50 | -0.001 | [-0.006, 0.004] | 0.019 | 8 / 7 / 35 | 2 |
| Merger Agreements | 50 | -0.003 | [-0.015, 0.006] | 0.039 | 4 / 3 / 43 | 5 |

## Noise floor (run-to-run, same 50 documents)

`sand42-noisefloor-correspondence-awq-1l4-c8` re-run against `sand42-50-correspondence-specialist-awq-1l4-c8` (identical settings, identical documents):

| Metric | Value |
| --- | ---: |
| Paired documents | 50 |
| Δ mean (should be ≈ 0) | -0.003 |
| 95% CI | [-0.022, 0.016] |
| SD of the difference | 0.066 |
| better / worse / tie | 1 / 2 / 47 |
| Paired n for Δ=0.05 | 14 |
| Paired n for Δ=0.03 | 39 |

**Quote no delta smaller than this floor.** Any cell-to-cell interval that contains 0 is inside the noise floor.

## Figures

![Quality](figures/cmp-quality.png)
![Cost](figures/cmp-cost.png)
![Latency](figures/cmp-latency.png)
![Throughput](figures/cmp-throughput.png)
![Gpu](figures/cmp-gpu.png)

_Generated 2026-10-12T22:59:20+00:00 by `sandbox run card --runbook sand42`._
