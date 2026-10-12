# Insurance Claims — 2× L4 · C8 · n=50

**Run:** `sand42-50-insurance-claims-specialist-awq-2l4-c8` · **Model:** Qwen/Qwen3-8B-AWQ · vLLM v0.29.0 · Modal `sandbox-vllm` · L4 @ $0.80/GPU-hr

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
| Run ID | `sand42-50-insurance-claims-specialist-awq-2l4-c8` |
| GPUs / replicas | 2 |
| Concurrency | 8 (4 per replica) |
| Documents | 50 |
| Spec hash | 9c87cb29… |
| **Time** |  |
| Wall (busy) | 119.72 s |
| GPU seconds | 120.68 s |
| Cold boot | 0.34 s |
| **Cost** |  |
| Busy-window GPU $ | $0.053211 |
| Billed GPU $ | $0.053636 |
| Billed seconds | 120.68 s |
| Idle $ | $0.017438 (39.23 s) |
| Cost per document | $0.001073 |
| Cost per ok document | $0.001073 |
| Cost per 1M tokens | $0.2881 |
| **Tokens** |  |
| Prompt tokens | 165,315 |
| Completion tokens | 20,870 (11.2%) |
| Total tokens | 186,185 |
| Tokens per document | 3,724 |
| Per document: instructions + template | 2,710 (72.8%) |
| Per document: document text | 597 (16.0%) |
| Per document: output | 417 (11.2%) |
| Instruction tokens per model call | 2,710 over 50 calls |
| Token split basis | fit across documents, 4.47 chars/token |
| Completion p95 / max (ok docs) | 599 / 1,816 |
| **Throughput** |  |
| Tokens / second | 1,555.1 |
| Tokens / second per L4 | 777.6 |
| Documents / minute | 25.06 |
| **Latency (per document, ok rows)** |  |
| Mean | 12.88 s |
| p50 | 11.40 s |
| p95 | 18.56 s |
| Max | 49.90 s |
| **Engine (vLLM /metrics)** |  |
| Parallelism (Σ latency ÷ wall) | 5.38× of 8 |
| Slot occupancy | 67.2% |
| Coverage | replicas observed: 2 of 2 |
| Requests per replica (this run) | 26 / 24 |
| Mean TTFT per replica | 0.703 s / 0.657 s |
| Prefix-cache hit per replica | 58.8% / 55.5% |
| Preemptions per replica (this run) | 0 / 0 |
| Length-capped finishes per replica (this run) | 0 / 0 |
| **GPU hardware (nvidia-smi)** | 40 samples · serving-replica nvidia-smi |
| GPU utilization | 75.3 % mean (p95 100.0 / peak 100.0 / min 0.0) |
| Sampling coverage | 100.0 % |
| GPU power draw | 63.0 W (min 32.4 / max 74.0) of 72 W cap |
| GPU memory bandwidth | 73.0 % (min 0.0 / max 100.0) |
| GPU SM clock | 1,518 MHz (min 930 / max 2,040) |
| GPU temperature | 75.8 C (min 69.0 / max 84.0) |
| GPU memory used | 20,997 MiB (min 20,996 / max 20,998) |
| **Quality** |  |
| Overall extraction score | 0.6703 (sd 0.064) |
| Score min / max | 0.5663 / 0.8178 |
| Scoring method | `suite` |
| Schema-valid rate | 0.30 |
| Parse errors | 0 |
| Errors | 0 / 50 |

## Figure

![Insurance Claims run dashboard](sand42-50-insurance-claims-specialist-awq-2l4-c8.card.png)

## Per-document results

| # | Document | OK | Score | Latency (s) | Prompt tok | Completion tok | Error |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `DOC-2aea7f6dc44b37e1` | yes | 0.7741 | 11.2 | 2835 | 357 | — |
| 2 | `DOC-2a55a2b5324659f8` | yes | 0.8098 | 11.2 | 2865 | 352 | — |
| 3 | `DOC-158c0b74df673b81` | yes | 0.6442 | 11.2 | 2939 | 369 | — |
| 4 | `DOC-2a33a6c34834e769` | yes | 0.6298 | 11.6 | 2953 | 337 | — |
| 5 | `DOC-629fb5789dfd10ca` | yes | 0.7979 | 12.5 | 2836 | 348 | — |
| 6 | `DOC-e2a58ed4c02470c0` | yes | 0.7812 | 13.4 | 2835 | 365 | — |
| 7 | `DOC-e7c196f508907c6f` | yes | 0.7830 | 13.4 | 2834 | 363 | — |
| 8 | `DOC-991cb72cb83c7a6c` | yes | 0.6442 | 13.5 | 2941 | 372 | — |
| 9 | `DOC-9ba0a3d4c680b976` | yes | 0.6398 | 10.0 | 2982 | 334 | — |
| 10 | `DOC-9a6f58879fcb3367` | yes | 0.6442 | 10.3 | 2946 | 359 | — |
| 11 | `DOC-968c9605eab0a87d` | yes | 0.6442 | 11.0 | 2942 | 350 | — |
| 12 | `DOC-997823d9605a4a59` | yes | 0.6442 | 11.3 | 2973 | 362 | — |
| 13 | `DOC-ef79520b2f50217b` | yes | 0.6892 | 11.0 | 3138 | 382 | — |
| 14 | `DOC-5c4e70db54374e72` | yes | 0.6874 | 11.5 | 3151 | 399 | — |
| 15 | `DOC-2435c398b95844bc` | yes | 0.6879 | 13.7 | 3080 | 478 | — |
| 16 | `DOC-5b1e8e2aed95c089` | yes | 0.6825 | 15.9 | 3123 | 543 | — |
| 17 | `DOC-00d28a1df0e3f6ba` | yes | 0.6971 | 7.5 | 2812 | 259 | — |
| 18 | `DOC-9051d4cf8d7ab452` | yes | 0.7100 | 10.8 | 3115 | 352 | — |
| 19 | `DOC-728d06b610b25244` | yes | 0.7043 | 7.5 | 2804 | 273 | — |
| 20 | `DOC-e4b1466ee8d1ff19` | yes | 0.7037 | 11.5 | 3113 | 399 | — |
| 21 | `DOC-5060222215c75aa6` | yes | 0.6745 | 8.9 | 2801 | 297 | — |
| 22 | `DOC-00ccdcb0154a8629` | yes | 0.6228 | 8.6 | 2812 | 281 | — |
| 23 | `DOC-f5e6c0de5f1d8593` | yes | 0.6487 | 9.2 | 2812 | 309 | — |
| 24 | `DOC-d8df43ed4d8faf89` | yes | 0.6888 | 15.4 | 3107 | 529 | — |
| 25 | `DOC-c34baab0b5fe378a` | yes | 0.6899 | 8.7 | 2807 | 280 | — |
| 26 | `DOC-cbfcdb6f42cf2ae6` | yes | 0.6872 | 8.6 | 2806 | 275 | — |
| 27 | `DOC-6f6fc9762418a70f` | yes | 0.7048 | 9.2 | 2811 | 294 | — |
| 28 | `DOC-29e384939c31d44a` | yes | 0.6131 | 9.4 | 3010 | 306 | — |
| 29 | `DOC-2d7cc160b78a69c5` | yes | 0.6442 | 11.0 | 2979 | 378 | — |
| 30 | `DOC-0cdb706a0cdbe3b6` | yes | 0.6265 | 10.8 | 2981 | 386 | — |
| 31 | `DOC-87c0c53132830a6c` | yes | 0.6265 | 11.3 | 2993 | 397 | — |
| 32 | `DOC-4e21681f375a247d` | yes | 0.6426 | 11.4 | 2985 | 400 | — |
| 33 | `DOC-27b23fd94cc70d9d` | yes | 0.6052 | 9.9 | 2890 | 353 | — |
| 34 | `DOC-364435343e0a2250` | yes | 0.6474 | 11.4 | 3020 | 393 | — |
| 35 | `DOC-93c8d133c296d536` | yes | 0.5663 | 9.1 | 2879 | 325 | — |
| 36 | `DOC-3ae2dc5d624e2120` | yes | 0.5999 | 10.8 | 2871 | 347 | — |
| 37 | `DOC-7bd9dbc1b39ad41d` | yes | 0.6031 | 19.9 | 3171 | 626 | — |
| 38 | `DOC-91da307f80433ae3` | yes | 0.5796 | 12.1 | 2894 | 358 | — |
| 39 | `DOC-44bcd388c4710b71` | yes | 0.5663 | 11.6 | 2884 | 346 | — |
| 40 | `DOC-90338506fc792f32` | yes | 0.5823 | 13.5 | 2882 | 372 | — |
| 41 | `DOC-164aa748f84cef54` | yes | 0.5810 | 13.6 | 2911 | 382 | — |
| 42 | `DOC-73d64bbeb296bd95` | yes | 0.6198 | 18.6 | 4524 | 542 | — |
| 43 | `DOC-7f1f866b022cee63` | yes | 0.7873 | 18.1 | 4985 | 510 | — |
| 44 | `DOC-384665a051d0fcd6` | yes | 0.6798 | 17.6 | 5208 | 532 | — |
| 45 | `DOC-85314478b81710d9` | yes | 0.6287 | 13.9 | 5285 | 426 | — |
| 46 | `DOC-ab18f15b7a51f1ab` | yes | 0.7490 | 15.6 | 5538 | 459 | — |
| 47 | `DOC-1076ac5b4b0df386` | yes | 0.6569 | 13.6 | 4482 | 429 | — |
| 48 | `DOC-6dcc0b9ba494c25b` | yes | 0.8178 | 15.9 | 5114 | 570 | — |
| 49 | `DOC-5b97ae3f8558703c` | yes | 0.6912 | 16.4 | 4565 | 599 | — |
| 50 | `DOC-02f77aa77391a8c2` | yes | 0.6864 | 49.9 | 5091 | 1816 | — |

_Generated 2026-10-12T17:17:13+00:00 by `sandbox run card`. Machine-readable twin: `sand42-50-insurance-claims-specialist-awq-2l4-c8.card.json`._
