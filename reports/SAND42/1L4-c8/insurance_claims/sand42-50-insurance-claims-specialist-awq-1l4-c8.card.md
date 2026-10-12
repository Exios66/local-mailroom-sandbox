# Insurance Claims — 1× L4 · C8 · n=50

**Run:** `sand42-50-insurance-claims-specialist-awq-1l4-c8` · **Model:** Qwen/Qwen3-8B-AWQ · vLLM v0.29.0 · Modal `sandbox-vllm` · L4 @ $0.80/GPU-hr

## Conditions

| Condition | Value |
| --- | --- |
| Task | insurance_claims_specialist |
| Prompt | insurance_claims_specialist_simplified |
| Temperature | 0.1 (vendored call site) |
| Output cap (max_tokens) | 8,192 |
| Input cap (max_input_chars) | 13,500 |
| Job retries | 2 |
| Dataset | Lucius-Morningstar/mailroom-dataset ground_truth @ ed7576b6, split=all, seed 42 |
| Draw | 50 docs (fingerprint f4fdcee45e7f) |
| Engine | awq_marlin · fp8 KV · CUDA graphs [1, 2, 4, 8, 16] · prefix caching on · thinking off |
| Admission | max_model_len 32768 · max_num_seqs 16 per replica · max_inputs 32 |

## Score & cost card

| Metric | Value |
| --- | ---: |
| **Run** |  |
| Run ID | `sand42-50-insurance-claims-specialist-awq-1l4-c8` |
| GPUs / replicas | 1 |
| Concurrency | 8 (8 per replica) |
| Documents | 50 |
| Spec hash | 8f77e131… |
| **Time** |  |
| Wall (busy) | 129.66 s |
| GPU seconds | 129.35 s |
| Cold boot | 0.47 s |
| **Cost** |  |
| Busy-window GPU $ | $0.028813 |
| Billed GPU $ | $0.028744 |
| Billed seconds | 129.35 s |
| Idle $ | $0.006981 (31.41 s) |
| Cost per document | $0.000575 |
| Cost per ok document | $0.000575 |
| Cost per 1M tokens | $0.1541 |
| **Tokens** |  |
| Prompt tokens | 165,315 |
| Completion tokens | 21,251 (11.4%) |
| Total tokens | 186,566 |
| Tokens per document | 3,731 |
| Per document: instructions + template | 2,710 (72.6%) |
| Per document: document text | 597 (16.0%) |
| Per document: output | 425 (11.4%) |
| Instruction tokens per model call | 2,710 over 50 calls |
| Token split basis | fit across documents, 4.47 chars/token |
| Completion p95 / max (ok docs) | 625 / 1,369 |
| **Throughput** |  |
| Tokens / second | 1,438.9 |
| Tokens / second per L4 | 1,438.9 |
| Documents / minute | 23.14 |
| **Latency (per document, ok rows)** |  |
| Mean | 15.72 s |
| p50 | 13.58 s |
| p95 | 24.58 s |
| Max | 45.85 s |
| **Engine (vLLM /metrics)** |  |
| Parallelism (Σ latency ÷ wall) | 6.06× of 8 |
| Slot occupancy | 75.8% |
| Coverage | replicas observed: 1 of 1 |
| Requests per replica (this run) | 50 |
| Mean TTFT per replica | 0.897 s |
| Prefix-cache hit per replica | 58.4% |
| Preemptions per replica (this run) | 0 |
| Length-capped finishes per replica (this run) | 0 |
| **GPU hardware (nvidia-smi)** | 18 samples · serving-replica nvidia-smi |
| GPU utilization | 92.8 % mean (p95 99.0 / peak 99.0 / min 0.0) |
| Sampling coverage | 94.8 % |
| GPU power draw | 69.4 W (min 30.2 / max 73.4) |
| GPU memory bandwidth | not captured |
| GPU SM clock | not captured |
| GPU temperature | 60.3 C (min 49.0 / max 66.0) |
| GPU memory used | 21,023 MiB (min 21,023 / max 21,023) |
| **Quality** |  |
| Overall extraction score | 0.6695 (sd 0.060) |
| Score min / max | 0.5663 / 0.8098 |
| Scoring method | `suite` |
| Schema-valid rate | 0.30 |
| Parse errors | 0 |
| Errors | 0 / 50 |

## Figure

![Insurance Claims run dashboard](sand42-50-insurance-claims-specialist-awq-1l4-c8.card.png)

## Per-document results

| # | Document | OK | Score | Latency (s) | Prompt tok | Completion tok | Error |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `DOC-2a33a6c34834e769` | yes | 0.6298 | 13.2 | 2953 | 341 | — |
| 2 | `DOC-e7c196f508907c6f` | yes | 0.7830 | 13.2 | 2834 | 362 | — |
| 3 | `DOC-158c0b74df673b81` | yes | 0.6442 | 13.2 | 2939 | 362 | — |
| 4 | `DOC-629fb5789dfd10ca` | yes | 0.7979 | 13.2 | 2836 | 361 | — |
| 5 | `DOC-2a55a2b5324659f8` | yes | 0.8098 | 13.2 | 2865 | 347 | — |
| 6 | `DOC-e2a58ed4c02470c0` | yes | 0.7671 | 13.3 | 2835 | 366 | — |
| 7 | `DOC-991cb72cb83c7a6c` | yes | 0.6442 | 13.4 | 2941 | 374 | — |
| 8 | `DOC-2aea7f6dc44b37e1` | yes | 0.7741 | 13.7 | 2835 | 387 | — |
| 9 | `DOC-9ba0a3d4c680b976` | yes | 0.6398 | 12.5 | 2982 | 334 | — |
| 10 | `DOC-968c9605eab0a87d` | yes | 0.6442 | 13.0 | 2942 | 354 | — |
| 11 | `DOC-9a6f58879fcb3367` | yes | 0.6487 | 14.3 | 2946 | 375 | — |
| 12 | `DOC-997823d9605a4a59` | yes | 0.6442 | 14.5 | 2973 | 382 | — |
| 13 | `DOC-ef79520b2f50217b` | yes | 0.6892 | 14.2 | 3138 | 390 | — |
| 14 | `DOC-2435c398b95844bc` | yes | 0.6795 | 17.8 | 3080 | 478 | — |
| 15 | `DOC-5b1e8e2aed95c089` | yes | 0.6873 | 19.9 | 3123 | 542 | — |
| 16 | `DOC-5c4e70db54374e72` | yes | 0.6763 | 21.0 | 3151 | 573 | — |
| 17 | `DOC-00d28a1df0e3f6ba` | yes | 0.6971 | 9.1 | 2812 | 261 | — |
| 18 | `DOC-5060222215c75aa6` | yes | 0.7412 | 10.1 | 2801 | 296 | — |
| 19 | `DOC-9051d4cf8d7ab452` | yes | 0.7100 | 13.4 | 3115 | 366 | — |
| 20 | `DOC-728d06b610b25244` | yes | 0.7043 | 9.6 | 2804 | 273 | — |
| 21 | `DOC-e4b1466ee8d1ff19` | yes | 0.6970 | 16.3 | 3113 | 468 | — |
| 22 | `DOC-00ccdcb0154a8629` | yes | 0.6228 | 9.8 | 2812 | 281 | — |
| 23 | `DOC-f5e6c0de5f1d8593` | yes | 0.7060 | 11.4 | 2812 | 327 | — |
| 24 | `DOC-d8df43ed4d8faf89` | yes | 0.6888 | 18.3 | 3107 | 529 | — |
| 25 | `DOC-c34baab0b5fe378a` | yes | 0.6232 | 10.7 | 2807 | 286 | — |
| 26 | `DOC-cbfcdb6f42cf2ae6` | yes | 0.6872 | 10.7 | 2806 | 285 | — |
| 27 | `DOC-6f6fc9762418a70f` | yes | 0.7123 | 11.4 | 2811 | 310 | — |
| 28 | `DOC-29e384939c31d44a` | yes | 0.6131 | 11.4 | 3010 | 306 | — |
| 29 | `DOC-2d7cc160b78a69c5` | yes | 0.6183 | 13.1 | 2979 | 371 | — |
| 30 | `DOC-0cdb706a0cdbe3b6` | yes | 0.6131 | 12.6 | 2981 | 363 | — |
| 31 | `DOC-87c0c53132830a6c` | yes | 0.6265 | 14.1 | 2993 | 410 | — |
| 32 | `DOC-4e21681f375a247d` | yes | 0.6426 | 13.5 | 2985 | 400 | — |
| 33 | `DOC-364435343e0a2250` | yes | 0.6474 | 13.2 | 3020 | 393 | — |
| 34 | `DOC-27b23fd94cc70d9d` | yes | 0.6052 | 11.8 | 2890 | 353 | — |
| 35 | `DOC-3ae2dc5d624e2120` | yes | 0.5999 | 12.5 | 2871 | 347 | — |
| 36 | `DOC-7bd9dbc1b39ad41d` | yes | 0.6036 | 22.0 | 3171 | 625 | — |
| 37 | `DOC-93c8d133c296d536` | yes | 0.5663 | 14.0 | 2879 | 338 | — |
| 38 | `DOC-91da307f80433ae3` | yes | 0.5796 | 15.5 | 2894 | 358 | — |
| 39 | `DOC-44bcd388c4710b71` | yes | 0.5837 | 16.9 | 2884 | 374 | — |
| 40 | `DOC-90338506fc792f32` | yes | 0.5956 | 17.6 | 2882 | 367 | — |
| 41 | `DOC-164aa748f84cef54` | yes | 0.5810 | 19.0 | 2911 | 394 | — |
| 42 | `DOC-73d64bbeb296bd95` | yes | 0.6198 | 24.6 | 4524 | 544 | — |
| 43 | `DOC-7f1f866b022cee63` | yes | 0.7309 | 22.5 | 4985 | 500 | — |
| 44 | `DOC-384665a051d0fcd6` | yes | 0.6798 | 21.8 | 5208 | 505 | — |
| 45 | `DOC-85314478b81710d9` | yes | 0.6844 | 17.2 | 5285 | 421 | — |
| 46 | `DOC-ab18f15b7a51f1ab` | yes | 0.7446 | 20.5 | 5538 | 495 | — |
| 47 | `DOC-1076ac5b4b0df386` | yes | 0.6569 | 16.2 | 4482 | 429 | — |
| 48 | `DOC-6dcc0b9ba494c25b` | yes | 0.7467 | 18.8 | 5114 | 576 | — |
| 49 | `DOC-02f77aa77391a8c2` | yes | 0.6963 | 45.9 | 5091 | 1369 | — |
| 50 | `DOC-5b97ae3f8558703c` | yes | 0.6912 | 27.1 | 4565 | 1003 | — |

_Generated 2026-10-12T06:10:28+00:00 by `sandbox run card`. Machine-readable twin: `sand42-50-insurance-claims-specialist-awq-1l4-c8.card.json`._
