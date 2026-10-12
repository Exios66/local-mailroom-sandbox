# Insurance Claims — 1× L4 · C16 · n=50

**Run:** `sand42-50-insurance-claims-specialist-awq-1l4-c16` · **Model:** Qwen/Qwen3-8B-AWQ · vLLM v0.29.0 · Modal `sandbox-vllm` · L4 @ $0.80/GPU-hr

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
| Run ID | `sand42-50-insurance-claims-specialist-awq-1l4-c16` |
| GPUs / replicas | 1 |
| Concurrency | 16 (16 per replica) |
| Documents | 50 |
| Spec hash | 4ea90e8a… |
| **Time** |  |
| Wall (busy) | 105.60 s |
| GPU seconds | 120.70 s |
| Cold boot | 0.28 s |
| **Cost** |  |
| Busy-window GPU $ | $0.023466 |
| Billed GPU $ | $0.026822 |
| Billed seconds | 120.70 s |
| Idle $ | $0.008282 (37.27 s) |
| Cost per document | $0.000536 |
| Cost per ok document | $0.000536 |
| Cost per 1M tokens | $0.1442 |
| **Tokens** |  |
| Prompt tokens | 165,315 |
| Completion tokens | 20,749 (11.2%) |
| Total tokens | 186,064 |
| Tokens per document | 3,721 |
| Per document: instructions + template | 2,710 (72.8%) |
| Per document: document text | 597 (16.0%) |
| Per document: output | 415 (11.2%) |
| Instruction tokens per model call | 2,710 over 50 calls |
| Token split basis | fit across documents, 4.47 chars/token |
| Completion p95 / max (ok docs) | 578 / 1,406 |
| **Throughput** |  |
| Tokens / second | 1,762.0 |
| Tokens / second per L4 | 1,762.0 |
| Documents / minute | 28.41 |
| **Latency (per document, ok rows)** |  |
| Mean | 21.86 s |
| p50 | 20.48 s |
| p95 | 30.28 s |
| Max | 47.70 s |
| **Engine (vLLM /metrics)** |  |
| Parallelism (Σ latency ÷ wall) | 10.35× of 16 |
| Slot occupancy | 64.7% |
| Coverage | replicas observed: 1 of 1 |
| Requests per replica (this run) | 50 |
| Mean TTFT per replica | 1.804 s |
| Prefix-cache hit per replica | 58.4% |
| Preemptions per replica (this run) | 0 |
| Length-capped finishes per replica (this run) | 0 |
| **GPU hardware (nvidia-smi)** | 21 samples · serving-replica nvidia-smi |
| GPU utilization | 74.6 % mean (p95 100.0 / peak 100.0 / min 0.0) |
| Sampling coverage | 100.0 % |
| GPU power draw | 61.7 W (min 31.8 / max 73.6) of 72 W cap |
| GPU memory bandwidth | 66.9 % (min 0.0 / max 100.0) |
| GPU SM clock | 1,496 MHz (min 990 / max 2,040) |
| GPU temperature | 75.2 C (min 70.0 / max 82.0) |
| GPU memory used | 21,025 MiB (min 21,024 / max 21,026) |
| **Quality** |  |
| Overall extraction score | 0.6647 (sd 0.063) |
| Score min / max | 0.5579 / 0.8098 |
| Scoring method | `suite` |
| Schema-valid rate | 0.28 |
| Parse errors | 0 |
| Errors | 0 / 50 |

## Figure

![Insurance Claims run dashboard](sand42-50-insurance-claims-specialist-awq-1l4-c16.card.png)

## Per-document results

| # | Document | OK | Score | Latency (s) | Prompt tok | Completion tok | Error |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `DOC-9ba0a3d4c680b976` | yes | 0.6398 | 19.1 | 2982 | 334 | — |
| 2 | `DOC-2aea7f6dc44b37e1` | yes | 0.7741 | 19.1 | 2835 | 353 | — |
| 3 | `DOC-2a33a6c34834e769` | yes | 0.6298 | 19.1 | 2953 | 341 | — |
| 4 | `DOC-629fb5789dfd10ca` | yes | 0.7944 | 19.1 | 2836 | 353 | — |
| 5 | `DOC-2a55a2b5324659f8` | yes | 0.8098 | 19.1 | 2865 | 346 | — |
| 6 | `DOC-e7c196f508907c6f` | yes | 0.7830 | 19.2 | 2834 | 360 | — |
| 7 | `DOC-997823d9605a4a59` | yes | 0.6442 | 19.2 | 2973 | 364 | — |
| 8 | `DOC-158c0b74df673b81` | yes | 0.6442 | 19.2 | 2939 | 367 | — |
| 9 | `DOC-9a6f58879fcb3367` | yes | 0.6442 | 19.4 | 2946 | 374 | — |
| 10 | `DOC-968c9605eab0a87d` | yes | 0.6442 | 19.4 | 2942 | 367 | — |
| 11 | `DOC-e2a58ed4c02470c0` | yes | 0.7671 | 19.5 | 2835 | 366 | — |
| 12 | `DOC-991cb72cb83c7a6c` | yes | 0.6442 | 20.5 | 2941 | 374 | — |
| 13 | `DOC-5c4e70db54374e72` | yes | 0.6874 | 24.3 | 3151 | 404 | — |
| 14 | `DOC-ef79520b2f50217b` | yes | 0.6892 | 24.4 | 3138 | 401 | — |
| 15 | `DOC-2435c398b95844bc` | yes | 0.6898 | 27.5 | 3080 | 476 | — |
| 16 | `DOC-5b1e8e2aed95c089` | yes | 0.6826 | 30.3 | 3123 | 548 | — |
| 17 | `DOC-6f6fc9762418a70f` | yes | 0.7102 | 14.0 | 2811 | 255 | — |
| 18 | `DOC-00d28a1df0e3f6ba` | yes | 0.6971 | 14.6 | 2812 | 259 | — |
| 19 | `DOC-728d06b610b25244` | yes | 0.7043 | 15.6 | 2804 | 273 | — |
| 20 | `DOC-cbfcdb6f42cf2ae6` | yes | 0.6946 | 15.3 | 2806 | 272 | — |
| 21 | `DOC-00ccdcb0154a8629` | yes | 0.6228 | 15.8 | 2812 | 281 | — |
| 22 | `DOC-5060222215c75aa6` | yes | 0.6745 | 17.2 | 2801 | 293 | — |
| 23 | `DOC-c34baab0b5fe378a` | yes | 0.6232 | 17.0 | 2807 | 294 | — |
| 24 | `DOC-f5e6c0de5f1d8593` | yes | 0.6450 | 17.4 | 2812 | 297 | — |
| 25 | `DOC-29e384939c31d44a` | yes | 0.6131 | 16.3 | 3010 | 306 | — |
| 26 | `DOC-9051d4cf8d7ab452` | yes | 0.7100 | 20.4 | 3115 | 352 | — |
| 27 | `DOC-e4b1466ee8d1ff19` | yes | 0.7037 | 22.9 | 3113 | 402 | — |
| 28 | `DOC-7bd9dbc1b39ad41d` | yes | 0.6298 | 19.1 | 3171 | 379 | — |
| 29 | `DOC-2d7cc160b78a69c5` | yes | 0.6442 | 20.9 | 2979 | 396 | — |
| 30 | `DOC-87c0c53132830a6c` | yes | 0.6265 | 21.5 | 2993 | 397 | — |
| 31 | `DOC-d8df43ed4d8faf89` | yes | 0.6888 | 31.7 | 3107 | 528 | — |
| 32 | `DOC-0cdb706a0cdbe3b6` | yes | 0.6265 | 23.0 | 2981 | 381 | — |
| 33 | `DOC-93c8d133c296d536` | yes | 0.5663 | 21.0 | 2879 | 328 | — |
| 34 | `DOC-3ae2dc5d624e2120` | yes | 0.5999 | 22.9 | 2871 | 347 | — |
| 35 | `DOC-27b23fd94cc70d9d` | yes | 0.6052 | 23.1 | 2890 | 353 | — |
| 36 | `DOC-44bcd388c4710b71` | yes | 0.5663 | 23.1 | 2884 | 346 | — |
| 37 | `DOC-364435343e0a2250` | yes | 0.6474 | 26.1 | 3020 | 393 | — |
| 38 | `DOC-4e21681f375a247d` | yes | 0.6426 | 26.3 | 2985 | 400 | — |
| 39 | `DOC-91da307f80433ae3` | yes | 0.5796 | 24.0 | 2894 | 370 | — |
| 40 | `DOC-90338506fc792f32` | yes | 0.5823 | 23.8 | 2882 | 372 | — |
| 41 | `DOC-164aa748f84cef54` | yes | 0.5899 | 24.7 | 2911 | 404 | — |
| 42 | `DOC-7f1f866b022cee63` | yes | 0.7873 | 26.6 | 4985 | 509 | — |
| 43 | `DOC-73d64bbeb296bd95` | yes | 0.6023 | 29.6 | 4524 | 578 | — |
| 44 | `DOC-85314478b81710d9` | yes | 0.6332 | 19.4 | 5285 | 436 | — |
| 45 | `DOC-384665a051d0fcd6` | yes | 0.6831 | 24.9 | 5208 | 529 | — |
| 46 | `DOC-ab18f15b7a51f1ab` | yes | 0.7414 | 22.3 | 5538 | 495 | — |
| 47 | `DOC-1076ac5b4b0df386` | yes | 0.6236 | 18.1 | 4482 | 442 | — |
| 48 | `DOC-6dcc0b9ba494c25b` | yes | 0.7569 | 19.2 | 5114 | 539 | — |
| 49 | `DOC-5b97ae3f8558703c` | yes | 0.5579 | 29.4 | 4565 | 1009 | — |
| 50 | `DOC-02f77aa77391a8c2` | yes | 0.6864 | 47.7 | 5091 | 1406 | — |

_Generated 2026-10-12T17:17:06+00:00 by `sandbox run card`. Machine-readable twin: `sand42-50-insurance-claims-specialist-awq-1l4-c16.card.json`._
