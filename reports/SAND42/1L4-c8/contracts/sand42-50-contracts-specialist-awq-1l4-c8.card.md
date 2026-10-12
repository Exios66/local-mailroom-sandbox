# Contracts — 1× L4 · C8 · n=50

**Run:** `sand42-50-contracts-specialist-awq-1l4-c8` · **Model:** Qwen/Qwen3-8B-AWQ · vLLM v0.29.0 · Modal `sandbox-vllm` · L4 @ $0.80/GPU-hr

## Conditions

| Condition | Value |
| --- | --- |
| Task | contracts_specialist |
| Prompt | contracts_specialist_v33_simplified |
| Temperature | 0.7 (posture knob) |
| Output cap (max_tokens) | 8,192 |
| Input cap (max_input_chars) | 49,000 |
| Chunk window (chars) | 43000 |
| Chunk overlap (chars) | 6000 |
| Job retries | 2 |
| Dataset | Lucius-Morningstar/mailroom-dataset ground_truth @ ed7576b6, split=all, seed 42 |
| Draw | 50 docs (fingerprint 83eb6b1f2c7e) |
| Engine | awq_marlin · fp8 KV · CUDA graphs [1, 2, 4, 8, 16] · prefix caching on · thinking off |
| Admission | max_model_len 32768 · max_num_seqs 16 per replica · max_inputs 32 |

## Score & cost card

| Metric | Value |
| --- | ---: |
| **Run** |  |
| Run ID | `sand42-50-contracts-specialist-awq-1l4-c8` |
| GPUs / replicas | 1 |
| Concurrency | 8 (8 per replica) |
| Documents | 50 |
| Spec hash | b01173a2… |
| **Time** |  |
| Wall (busy) | 386.78 s |
| GPU seconds | 920.59 s |
| Cold boot | 0.38 s |
| **Cost** |  |
| Busy-window GPU $ | $0.085952 |
| Billed GPU $ | $0.204575 |
| Billed seconds | 920.59 s |
| Idle $ | not captured |
| Cost per document | $0.004092 |
| Cost per ok document | $0.004092 |
| Cost per 1M tokens | $0.2202 |
| **Tokens** |  |
| Prompt tokens | 799,423 |
| Completion tokens | 129,558 (13.9%) |
| Total tokens | 928,981 |
| Tokens per document | 18,580 |
| Per document: instructions + template | 4,313 (23.2%) |
| Per document: document text | 11,676 (62.8%) |
| Per document: output | 2,591 (13.9%) |
| Instruction tokens per model call | 2,537 over 85 calls |
| Token split basis | document chars ÷ 4.5 chars/token; instructions are the remainder |
| Completion p95 / max (ok docs) | 5,774 / 13,151 |
| **Throughput** |  |
| Tokens / second | 2,401.8 |
| Tokens / second per L4 | 2,401.8 |
| Documents / minute | 7.76 |
| **Latency (per document, ok rows)** |  |
| Mean | 138.28 s |
| p50 | 94.48 s |
| p95 | 316.42 s |
| Max | 687.82 s |
| **Engine (vLLM /metrics)** |  |
| Parallelism (Σ latency ÷ wall) | 17.88× of 8 |
| Slot occupancy | 223.4% |
| Coverage | replicas observed: 1 of 1 |
| Requests per replica (this run) | 85 |
| Mean TTFT per replica | 1.951 s |
| Prefix-cache hit per replica | 38.3% |
| Preemptions per replica (this run) | 0 |
| Length-capped finishes per replica (this run) | 0 |
| **GPU hardware (nvidia-smi)** | 139 samples · serving-replica nvidia-smi |
| GPU utilization | 97.6 % mean (p95 100.0 / peak 100.0 / min 0.0) |
| Sampling coverage | 100.0 % |
| GPU power draw | 71.4 W (min 32.1 / max 75.2) |
| GPU temperature | 73.0 C (min 57.0 / max 78.0) |
| GPU memory used | 21,026 MiB (min 21,023 / max 21,027) |
| **Quality** |  |
| Overall extraction score | 0.5790 (sd 0.123) |
| Score min / max | 0.2703 / 0.8182 |
| Scoring method | `suite+cuad` |
| Schema-valid rate | 1.00 |
| Parse errors | 0 |
| Errors | 0 / 50 |
| **Clause scoring (CUAD)** |  |
| Docs with CUAD labels | 45 |
| Micro precision / recall / F1 | 0.615 / 0.557 / 0.585 |
| Metadata value checks | 74 / 128 |
| Suite field score (mean) | not captured |

## Per-document results

| # | Document | OK | Score | Latency (s) | Prompt tok | Completion tok | Error |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `DOC-6b4cc54c8c4d796f` | yes | — | 38.9 | 4015 | 714 | — |
| 2 | `DOC-a9850db362f57916` | yes | — | 46.9 | 6764 | 863 | — |
| 3 | `DOC-b1aba7df0380a1b2` | yes | — | 62.2 | 5032 | 1235 | — |
| 4 | `DOC-fc9671ccde642e8d` | yes | — | 68.8 | 7936 | 1330 | — |
| 5 | `DOC-f5a54932794ef16e` | yes | 0.6667 | 75.3 | 5302 | 1413 | — |
| 6 | `DOC-3c07c9ccd9a01d6e` | yes | 0.6316 | 92.0 | 7428 | 1668 | — |
| 7 | `DOC-03529267ee75444d` | yes | 0.5714 | 75.1 | 10583 | 1312 | — |
| 8 | `DOC-e235bc9735f96335` | yes | 0.5217 | 62.9 | 10699 | 1068 | — |
| 9 | `DOC-6671a684f52f82a9` | yes | 0.4167 | 96.3 | 11320 | 1614 | — |
| 10 | `DOC-385a86c69f8e562c` | yes | 0.6154 | 125.7 | 6560 | 2278 | — |
| 11 | `DOC-b87880882e5fe354` | yes | — | 187.9 | 19278 | 3412 | — |
| 12 | `DOC-0752e0811f5f5eb7` | yes | 0.3810 | 196.8 | 41619 | 3560 | — |
| 13 | `DOC-0812d9d3e2b1baa0` | yes | 0.4444 | 145.5 | 18679 | 2591 | — |
| 14 | `DOC-593f2c6de770b84c` | yes | 0.6667 | 147.2 | 9228 | 2702 | — |
| 15 | `DOC-e4272758b561f8cd` | yes | 0.5556 | 82.7 | 6987 | 1493 | — |
| 16 | `DOC-f8b0d4bcbac60ca2` | yes | 0.5000 | 74.5 | 3824 | 1332 | — |
| 17 | `DOC-81c4ce12d907380c` | yes | 0.5714 | 83.3 | 7047 | 1477 | — |
| 18 | `DOC-4fb6419e37bff201` | yes | 0.6875 | 216.7 | 22234 | 3912 | — |
| 19 | `DOC-b83763aeff114369` | yes | 0.6207 | 93.8 | 7446 | 1776 | — |
| 20 | `DOC-9a36838df2878b37` | yes | 0.4348 | 66.4 | 8142 | 1255 | — |
| 21 | `DOC-2b510409d3b9a4a6` | yes | 0.6875 | 282.1 | 21668 | 5164 | — |
| 22 | `DOC-812192e392d8d410` | yes | 0.6000 | 155.3 | 5551 | 2834 | — |
| 23 | `DOC-9cee2e10b449a71c` | yes | 0.7568 | 194.8 | 21752 | 3597 | — |
| 24 | `DOC-73055dbb1e9f5f2f` | yes | 0.7111 | 316.4 | 49409 | 5774 | — |
| 25 | `DOC-e998c563b82122b9` | yes | 0.5263 | 95.1 | 10006 | 1653 | — |
| 26 | `DOC-1e22a2d4068b8650` | yes | 0.7143 | 92.3 | 7587 | 1592 | — |
| 27 | `DOC-27b649fe2f6fae8e` | yes | 0.7778 | 85.0 | 5464 | 1480 | — |
| 28 | `DOC-70f90b46b2c4f1a6` | yes | 0.6667 | 17.8 | 3154 | 361 | — |
| 29 | `DOC-035731e655e67aab` | yes | 0.4762 | 151.4 | 5207 | 2775 | — |
| 30 | `DOC-e29140d2e8e989be` | yes | 0.5000 | 521.8 | 45485 | 9573 | — |
| 31 | `DOC-1266801f2faad19f` | yes | 0.6829 | 219.6 | 33383 | 3969 | — |
| 32 | `DOC-1ddc9333769d27e4` | yes | 0.5714 | 73.3 | 4450 | 1332 | — |
| 33 | `DOC-712c3f92a0a56b77` | yes | 0.4444 | 271.6 | 56227 | 4948 | — |
| 34 | `DOC-62b300182901e850` | yes | 0.5455 | 136.0 | 33346 | 2527 | — |
| 35 | `DOC-dfb4e69a3ab10dc9` | yes | 0.5263 | 72.6 | 7378 | 1289 | — |
| 36 | `DOC-fe06800cc62e5e19` | yes | 0.6364 | 84.1 | 8619 | 1580 | — |
| 37 | `DOC-472f423cdf0819ef` | yes | 0.7500 | 57.8 | 4656 | 1107 | — |
| 38 | `DOC-186145066ab191fa` | yes | 0.5000 | 44.8 | 3718 | 921 | — |
| 39 | `DOC-f45b328fd8a54c8b` | yes | 0.6250 | 52.4 | 4608 | 1077 | — |
| 40 | `DOC-c9d4c4f8ff433527` | yes | 0.5217 | 73.1 | 7730 | 1402 | — |
| 41 | `DOC-8993ad1085e08bd0` | yes | 0.7692 | 262.4 | 22402 | 4965 | — |
| 42 | `DOC-4b57f485708ab60b` | yes | 0.4000 | 78.8 | 6639 | 1473 | — |
| 43 | `DOC-8f737e9fec8f24f0` | yes | 0.5000 | 218.0 | 35815 | 4013 | — |
| 44 | `DOC-e0d31c39359cb803` | yes | 0.2703 | 118.6 | 6879 | 2351 | — |
| 45 | `DOC-01849fa3020a5ac1` | yes | 0.5000 | 52.6 | 4173 | 1117 | — |
| 46 | `DOC-be1eccde5bae9c82` | yes | 0.4800 | 101.8 | 9330 | 2092 | — |
| 47 | `DOC-e218d39bb2f3c5ef` | yes | 0.4000 | 140.5 | 19923 | 2967 | — |
| 48 | `DOC-dfd20f94bb76b6e4` | yes | 0.6923 | 114.4 | 21000 | 2574 | — |
| 49 | `DOC-53e364f030a30b5c` | yes | 0.7170 | 687.8 | 94991 | 13151 | — |
| 50 | `DOC-dbe52fd78e44b0ef` | yes | 0.8182 | 102.9 | 18750 | 2895 | — |

_Generated 2026-10-12T02:58:55+00:00 by `sandbox run card`. Machine-readable twin: `sand42-50-contracts-specialist-awq-1l4-c8.card.json`._
