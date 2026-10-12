# SAND-042 · paired comparison across the four cells

All four cells score the **identical 250 documents** (5 specialists × 50, one subclass-stratified draw), so every cell-to-cell delta below is **paired**: the unit of analysis is the per-document score difference. Intervals are 95% percentile bootstrap over documents; the last column is the paired n that Δ = 0.05 would need at 80% power.

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

## 2l4-c16 (2× L4 · C16 · 8/replica) vs 1l4-c8

| Class | Paired n | Δ mean | 95% CI | SD_diff | better / worse / tie | n for Δ=0.05 |
| --- | ---: | ---: | --- | ---: | --- | ---: |
| Corporate Records | 50 | +0.001 | [-0.018, 0.021] | 0.069 | 4 / 4 / 42 | 15 |
| Correspondence | 50 | -0.003 | [-0.029, 0.021] | 0.091 | 3 / 5 / 42 | 27 |
| Insurance Claims | 50 | -0.001 | [-0.007, 0.003] | 0.018 | 14 / 11 / 25 | 2 |

## Noise floor (run-to-run, same 50 documents)

_Not measured._ Run `sand42-noise-floor` (blocked until spend is approved) on the same 50 correspondence documents. Until then the SAND-037/39 floor in `docs/BENCHMARK-PROGRAM.md` §3 is the prior — it was measured on a different draw, so treat it as indicative only.

## Figures

![Quality](figures/cmp-quality.png)
![Cost](figures/cmp-cost.png)
![Latency](figures/cmp-latency.png)
![Throughput](figures/cmp-throughput.png)
![Gpu](figures/cmp-gpu.png)

_Generated 2026-10-12T07:01:18+00:00 by `sandbox run card --runbook sand42`._
