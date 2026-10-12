# Serving — `sand42-50-merger-specialist-awq-2l4-c32`

Stem `RUN-50-MERGER-AWQ-2L4-C32`. Model `Qwen/Qwen3-8B-AWQ`. TTFT is never inferred.

| metric | value |
| --- | --- |
| run_id | `sand42-50-merger-specialist-awq-2l4-c32` |
| task | `merger_agreement_specialist` |
| model | `Qwen/Qwen3-8B-AWQ` |
| GPU | `L4` ×2 |
| n | 50 |
| concurrency | 32 |
| wall_seconds | 1972.327 |
| cold_boot_seconds | 0.238 |
| gpu_seconds | 1972.565 |
| estimated_gpu_cost_usd | 0.876696 |
| **gpu_cost_per_document** | **0.017534** |
| token-proxy cost_usd | 0.186557 |
| latency mean / p50 / p95 / max (s) | 1025.409344 / 987.541598 / 1685.641352 / 1959.188491 |
| latency_sum_seconds | 51270.467 |
| latency_sum_over_wall | 25.99 |
| prompt_tokens | 4867606 |
| completion_tokens | 311760 |
| total_tokens | 5179366 |
| tokens_per_second | 2626.02 |
| slot_utilization | 0.8123 |
| busy_slot_seconds | 1602.202 |
| ttft_seconds | — |
| ttft_note | TTFT never inferred (served locally; do not infer from e2e) |

Machine-readable sibling: same stem with `.serving.json`.
