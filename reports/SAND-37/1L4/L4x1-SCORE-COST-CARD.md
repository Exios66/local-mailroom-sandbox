# SAND-37 — 1× L4 · C8 score & cost card

**Cells reported:** 5 of 10 · **Runbook:** `grid-1l4` · **Model:** Qwen/Qwen3-8B-AWQ · L4 @ $0.80/GPU-hr

## Shared conditions

| Condition | Value |
| --- | --- |
| Engine | awq_marlin · fp8 KV · CUDA graphs [1, 2, 4, 8, 16] · prefix caching on · thinking off |
| Admission | max_model_len 32768 · max_num_seqs 16 per replica · max_inputs 32 |
| Fleet | 1 replica(s) · client concurrency 8 |
| Dataset | Lucius-Morningstar/mailroom-dataset ground_truth @ ed7576b6, split=all, seed 42, one class bucket (n=20 nested in n=50) |
| Output cap | max_tokens 8,192 |
| Temperature | 0.7 contracts and merger (JSON-schema grammar); 0.1 elsewhere (vendored call site) |

## Pooled totals

| Metric | n = 20 | n = 50 | All cells |
| --- | ---: | ---: | ---: |
| Cells reported | 5 | 0 | 5 |
| Documents ok / total | 97 / 100 | 0 / 0 | 97 / 100 |
| Error rate | 3.0% | not captured | 3.0% |
| Wall (Σ busy) | 686.6 s | not captured | 686.6 s |
| Busy-window GPU $ | $0.1526 | not captured | $0.1526 |
| Cost per document (pooled) | $0.001526 | not captured | $0.001526 |
| Cost per 1M tokens (pooled) | $0.2737 | not captured | $0.2737 |
| Tokens | 557,581 | 0 | 557,581 |
| Tokens / second (pooled) | 812.0 | not captured | 812.0 |
| Tokens / second per L4 | 812.0 | not captured | 812.0 |
| Documents / minute (pooled) | 8.74 | not captured | 8.74 |

## Per specialist · n = 20

| Metric | Correspondence | Insurance Claims | Corporate Records | Contracts | Merger Agreements |
| --- | ---: | ---: | ---: | ---: | ---: |
| **Status** | | | | | |
| Run ID | `grid-20-correspondence-specialist-awq-1l4` | `grid-20-insurance-claims-specialist-awq-1l4` | `grid-20-corporate-records-specialist-awq-1l4` | `grid-20-contracts-specialist-awq-1l4` | `grid-20-merger-specialist-awq-1l4-rerun` |
| Documents ok / total | 20 / 20 | 20 / 20 | 20 / 20 | 19 / 20 | 18 / 20 |
| Errors | 0 | 0 | 0 | LengthFinishReasonError 1 | LengthFinishReasonError 2 |
| **Time** | | | | | |
| Wall (busy) | 10.1 s | 37.8 s | 23.4 s | 299.3 s | 316.1 s |
| **Cost** | | | | | |
| Busy-window GPU $ | $0.0022 | $0.0084 | $0.0052 | $0.0665 | $0.0703 |
| Cost per document | $0.000112 | $0.000420 | $0.000260 | $0.003326 | $0.003513 |
| Cost per 1M tokens | $0.0442 | $0.1225 | $0.0515 | $0.4289 | $0.3846 |
| **Tokens** | | | | | |
| Total tokens | 50,542 | 68,536 | 100,791 | 155,054 | 182,658 |
| Completion share | 5.4% | 11.3% | 3.6% | 20.6% | 8.5% |
| Completion max (ok docs) | 296 | 968 | 247 | 4,860 | 1,661 |
| **Throughput** | | | | | |
| Tokens / second | 5,028.6 | 1,813.5 | 4,314.9 | 518.1 | 577.8 |
| Tokens / second per L4 | 5,028.6 | 1,813.5 | 4,314.9 | 518.1 | 577.8 |
| Documents / minute | 119.39 | 31.75 | 51.37 | 4.01 | 3.80 |
| **Latency** | | | | | |
| p50 / p95 | 5.8 / 7.9 s | 13.2 / 19.0 s | 14.4 / 20.5 s | 65.8 / 104.9 s | 50.5 / 66.1 s |
| Max | 12.2 s | 24.8 s | 20.7 s | 187.8 s | 113.3 s |
| **Engine** | | | | | |
| Slot occupancy | 140.1% | 88.9% | 152.3% | 63.4% | 61.4% |
| Mean TTFT per replica | 0.96 | 1.06 | 1.84 | 3.14 | 4.89 |
| Prefix-cache hit per replica | 67% | 61% | 47% | 43% | 31% |
| Length-capped finishes | 0 | 0 | 0 | 1 | 2 |
| **Quality** | | | | | |
| Overall extraction score | 0.3268 | 0.6836 | 0.4592 | 0.6307 | 0.0129 |
| Clause score | — | — | — | CUAD F1 0.597 | MAUD acc 1.4% |
| Schema-valid rate | 1.00 | 0.30 | 0.95 | 1.00 | 1.00 |

## Per specialist · n = 50

| Metric | Correspondence | Insurance Claims | Corporate Records | Contracts | Merger Agreements |
| --- | ---: | ---: | ---: | ---: | ---: |
| **Status** | | | | | |
| Run ID | not run | not run | not run | not run | not run |
| Documents ok / total | not run | not run | not run | not run | not run |
| Errors | not run | not run | not run | not run | not run |
| **Time** | | | | | |
| Wall (busy) | not run | not run | not run | not run | not run |
| **Cost** | | | | | |
| Busy-window GPU $ | not run | not run | not run | not run | not run |
| Cost per document | not run | not run | not run | not run | not run |
| Cost per 1M tokens | not run | not run | not run | not run | not run |
| **Tokens** | | | | | |
| Total tokens | not run | not run | not run | not run | not run |
| Completion share | not run | not run | not run | not run | not run |
| Completion max (ok docs) | not run | not run | not run | not run | not run |
| **Throughput** | | | | | |
| Tokens / second | not run | not run | not run | not run | not run |
| Tokens / second per L4 | not run | not run | not run | not run | not run |
| Documents / minute | not run | not run | not run | not run | not run |
| **Latency** | | | | | |
| p50 / p95 | not run | not run | not run | not run | not run |
| Max | not run | not run | not run | not run | not run |
| **Engine** | | | | | |
| Slot occupancy | not run | not run | not run | not run | not run |
| Mean TTFT per replica | not run | not run | not run | not run | not run |
| Prefix-cache hit per replica | not run | not run | not run | not run | not run |
| Length-capped finishes | not run | not run | not run | not run | not run |
| **Quality** | | | | | |
| Overall extraction score | not run | not run | not run | not run | not run |
| Clause score | not run | not run | not run | not run | not run |
| Schema-valid rate | not run | not run | not run | not run | not run |

## Per-run cards

| Specialist | n | Run ID | Card |
| --- | ---: | --- | --- |
| Correspondence | 20 | `grid-20-correspondence-specialist-awq-1l4` | [grid-20-correspondence-specialist-awq-1l4.card.md](correspondence/grid-20-correspondence-specialist-awq-1l4.card.md) |
| Insurance Claims | 20 | `grid-20-insurance-claims-specialist-awq-1l4` | [grid-20-insurance-claims-specialist-awq-1l4.card.md](insurance_claims/grid-20-insurance-claims-specialist-awq-1l4.card.md) |
| Corporate Records | 20 | `grid-20-corporate-records-specialist-awq-1l4` | [grid-20-corporate-records-specialist-awq-1l4.card.md](corporate_records/grid-20-corporate-records-specialist-awq-1l4.card.md) |
| Contracts | 20 | `grid-20-contracts-specialist-awq-1l4` | [grid-20-contracts-specialist-awq-1l4.card.md](contracts/grid-20-contracts-specialist-awq-1l4.card.md) |
| Merger Agreements | 20 | `grid-20-merger-specialist-awq-1l4-rerun` | [grid-20-merger-specialist-awq-1l4-rerun.card.md](merger_agreement/grid-20-merger-specialist-awq-1l4-rerun.card.md) |
| Correspondence | 50 | `grid-50-correspondence-specialist-awq-1l4` | not run |
| Insurance Claims | 50 | `grid-50-insurance-claims-specialist-awq-1l4` | not run |
| Corporate Records | 50 | `grid-50-corporate-records-specialist-awq-1l4` | not run |
| Contracts | 50 | `grid-50-contracts-specialist-awq-1l4` | not run |
| Merger Agreements | 50 | `grid-50-merger-specialist-awq-1l4` | not run |

_Generated 2026-10-01T01:17:16+00:00 by `sandbox run card --runbook grid-1l4` from the committed per-run `*.card.json`._
