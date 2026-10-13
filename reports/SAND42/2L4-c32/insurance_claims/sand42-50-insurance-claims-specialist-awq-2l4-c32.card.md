# Insurance Claims — 2× L4 · C32 · n=50

**Run:** `sand42-50-insurance-claims-specialist-awq-2l4-c32` · **Model:** Qwen/Qwen3-8B-AWQ · vLLM v0.29.0 · Modal `sandbox-vllm` · L4 @ $0.80/GPU-hr

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
| Run ID | `sand42-50-insurance-claims-specialist-awq-2l4-c32` |
| GPUs / replicas | 2 |
| Concurrency | 32 (16 per replica) |
| Documents | 50 |
| Spec hash | 676fd83f… |
| **Time** |  |
| Wall (busy) | 74.56 s |
| GPU seconds | 75.31 s |
| Cold boot | 0.26 s |
| **Cost** |  |
| Busy-window GPU $ | $0.033136 |
| Billed GPU $ | $0.033473 |
| Billed seconds | 75.31 s |
| Idle $ | $0.014751 (33.19 s) |
| Cost per document | $0.000669 |
| Cost per ok document | $0.000669 |
| Cost per 1M tokens | $0.1801 |
| **Tokens** |  |
| Prompt tokens | 165,315 |
| Completion tokens | 20,534 (11.0%) |
| Total tokens | 185,849 |
| Tokens per document | 3,717 |
| Per document: instructions + template | 2,710 (72.9%) |
| Per document: document text | 597 (16.0%) |
| Per document: output | 411 (11.0%) |
| Instruction tokens per model call | 2,710 over 50 calls |
| Token split basis | fit across documents, 4.47 chars/token |
| Completion p95 / max (ok docs) | 588 / 1,409 |
| **Throughput** |  |
| Tokens / second | 2,492.8 |
| Tokens / second per L4 | 1,246.4 |
| Documents / minute | 40.24 |
| **Latency (per document, ok rows)** |  |
| Mean | 26.47 s |
| p50 | 28.76 s |
| p95 | 42.37 s |
| Max | 44.68 s |
| **Engine (vLLM /metrics)** |  |
| Parallelism (Σ latency ÷ wall) | 17.75× of 32 |
| Slot occupancy | 55.5% |
| Coverage | replicas observed: 2 of 2 |
| Requests per replica (this run) | 38 / 12 |
| Mean TTFT per replica | 8.659 s / 0.798 s |
| Prefix-cache hit per replica | 59.2% / 51.0% |
| Preemptions per replica (this run) | 0 / 0 |
| Length-capped finishes per replica (this run) | 0 / 0 |
| **GPU hardware (nvidia-smi)** | 22 samples · serving-replica nvidia-smi |
| GPU utilization | 75.6 % mean (p95 100.0 / peak 100.0 / min 0.0) |
| Sampling coverage | 100.0 % |
| GPU power draw | 64.6 W (min 32.4 / max 72.7) of 72 W cap |
| GPU memory bandwidth | 70.3 % (min 0.0 / max 100.0) |
| GPU SM clock | 1,526 MHz (min 1,110 / max 2,040) |
| GPU temperature | 74.6 C (min 68.0 / max 79.0) |
| GPU memory used | 21,023 MiB (min 21,022 / max 21,024) |
| **Quality** |  |
| Overall extraction score | 0.6701 (sd 0.062) |
| Score min / max | 0.5663 / 0.8098 |
| Scoring method | `suite` |
| Schema-valid rate | 0.30 |
| Parse errors | 0 |
| Errors | 0 / 50 |
| **Paired n** |  |
| Documents a paired delta can use | 50 of 50 |

## Figure

![Insurance Claims run dashboard](sand42-50-insurance-claims-specialist-awq-2l4-c32.card.png)

## Per-document results

| # | Document | OK | Score | Latency (s) | Prompt tok | Completion tok | Error |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `DOC-e7c196f508907c6f` | yes | 0.7830 | 10.9 | 2834 | 362 | — |
| 2 | `DOC-2a55a2b5324659f8` | yes | 0.8098 | 10.9 | 2865 | 345 | — |
| 3 | `DOC-d8df43ed4d8faf89` | yes | 0.6888 | 14.9 | 3107 | 522 | — |
| 4 | `DOC-cbfcdb6f42cf2ae6` | yes | 0.6946 | 15.7 | 2806 | 286 | — |
| 5 | `DOC-c34baab0b5fe378a` | yes | 0.6899 | 15.7 | 2807 | 285 | — |
| 6 | `DOC-00ccdcb0154a8629` | yes | 0.6228 | 16.2 | 2812 | 281 | — |
| 7 | `DOC-5060222215c75aa6` | yes | 0.7412 | 17.1 | 2801 | 296 | — |
| 8 | `DOC-29e384939c31d44a` | yes | 0.6131 | 17.7 | 3010 | 306 | — |
| 9 | `DOC-2a33a6c34834e769` | yes | 0.6298 | 19.5 | 2953 | 338 | — |
| 10 | `DOC-629fb5789dfd10ca` | yes | 0.7979 | 20.0 | 2836 | 349 | — |
| 11 | `DOC-968c9605eab0a87d` | yes | 0.6442 | 20.9 | 2942 | 367 | — |
| 12 | `DOC-e2a58ed4c02470c0` | yes | 0.7857 | 21.2 | 2835 | 366 | — |
| 13 | `DOC-9a6f58879fcb3367` | yes | 0.6442 | 21.8 | 2946 | 374 | — |
| 14 | `DOC-ef79520b2f50217b` | yes | 0.6892 | 22.7 | 3138 | 382 | — |
| 15 | `DOC-2aea7f6dc44b37e1` | yes | 0.7741 | 23.0 | 2835 | 387 | — |
| 16 | `DOC-2d7cc160b78a69c5` | yes | 0.6442 | 23.5 | 2979 | 396 | — |
| 17 | `DOC-4e21681f375a247d` | yes | 0.6188 | 14.6 | 2985 | 371 | — |
| 18 | `DOC-5b1e8e2aed95c089` | yes | 0.6896 | 29.0 | 3123 | 547 | — |
| 19 | `DOC-728d06b610b25244` | yes | 0.7043 | 30.0 | 2804 | 273 | — |
| 20 | `DOC-5c4e70db54374e72` | yes | 0.6763 | 31.0 | 3151 | 590 | — |
| 21 | `DOC-3ae2dc5d624e2120` | yes | 0.5999 | 15.2 | 2871 | 338 | — |
| 22 | `DOC-7bd9dbc1b39ad41d` | yes | 0.6031 | 31.2 | 3171 | 588 | — |
| 23 | `DOC-f5e6c0de5f1d8593` | yes | 0.6487 | 31.6 | 2812 | 309 | — |
| 24 | `DOC-91da307f80433ae3` | yes | 0.5796 | 15.7 | 2894 | 367 | — |
| 25 | `DOC-00d28a1df0e3f6ba` | yes | 0.6971 | 32.4 | 2812 | 260 | — |
| 26 | `DOC-90338506fc792f32` | yes | 0.5956 | 15.6 | 2882 | 367 | — |
| 27 | `DOC-9ba0a3d4c680b976` | yes | 0.6398 | 34.0 | 2982 | 334 | — |
| 28 | `DOC-9051d4cf8d7ab452` | yes | 0.7100 | 35.6 | 3115 | 352 | — |
| 29 | `DOC-6f6fc9762418a70f` | yes | 0.7048 | 37.3 | 2811 | 291 | — |
| 30 | `DOC-158c0b74df673b81` | yes | 0.6442 | 38.2 | 2939 | 362 | — |
| 31 | `DOC-1076ac5b4b0df386` | yes | 0.6569 | 14.6 | 4482 | 428 | — |
| 32 | `DOC-ab18f15b7a51f1ab` | yes | 0.7414 | 17.0 | 5538 | 486 | — |
| 33 | `DOC-73d64bbeb296bd95` | yes | 0.6245 | 20.2 | 4524 | 531 | — |
| 34 | `DOC-991cb72cb83c7a6c` | yes | 0.6442 | 40.6 | 2941 | 374 | — |
| 35 | `DOC-997823d9605a4a59` | yes | 0.6442 | 42.1 | 2973 | 363 | — |
| 36 | `DOC-0cdb706a0cdbe3b6` | yes | 0.6131 | 42.1 | 2981 | 379 | — |
| 37 | `DOC-e4b1466ee8d1ff19` | yes | 0.7037 | 42.4 | 3113 | 403 | — |
| 38 | `DOC-87c0c53132830a6c` | yes | 0.6265 | 42.6 | 2993 | 410 | — |
| 39 | `DOC-5b97ae3f8558703c` | yes | 0.6912 | 14.4 | 4565 | 484 | — |
| 40 | `DOC-2435c398b95844bc` | yes | 0.6879 | 44.7 | 3080 | 453 | — |
| 41 | `DOC-93c8d133c296d536` | yes | 0.5663 | 31.0 | 2879 | 325 | — |
| 42 | `DOC-27b23fd94cc70d9d` | yes | 0.6052 | 32.7 | 2890 | 362 | — |
| 43 | `DOC-44bcd388c4710b71` | yes | 0.5663 | 30.3 | 2884 | 346 | — |
| 44 | `DOC-364435343e0a2250` | yes | 0.6474 | 36.8 | 3020 | 393 | — |
| 45 | `DOC-164aa748f84cef54` | yes | 0.5899 | 29.5 | 2911 | 393 | — |
| 46 | `DOC-85314478b81710d9` | yes | 0.6189 | 28.5 | 5285 | 445 | — |
| 47 | `DOC-7f1f866b022cee63` | yes | 0.7873 | 31.5 | 4985 | 509 | — |
| 48 | `DOC-384665a051d0fcd6` | yes | 0.6798 | 30.7 | 5208 | 504 | — |
| 49 | `DOC-6dcc0b9ba494c25b` | yes | 0.7569 | 29.0 | 5114 | 546 | — |
| 50 | `DOC-02f77aa77391a8c2` | yes | 0.6912 | 40.2 | 5091 | 1409 | — |

_Generated 2026-10-12T22:59:14+00:00 by `sandbox run card`. Machine-readable twin: `sand42-50-insurance-claims-specialist-awq-2l4-c32.card.json`._
