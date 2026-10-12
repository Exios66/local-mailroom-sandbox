# Insurance Claims — 2× L4 · C16 · n=50

**Run:** `sand42-50-insurance-claims-specialist-awq-2l4-c16` · **Model:** Qwen/Qwen3-8B-AWQ · vLLM v0.29.0 · Modal `sandbox-vllm-b` · L4 @ $0.80/GPU-hr

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
| Run ID | `sand42-50-insurance-claims-specialist-awq-2l4-c16` |
| GPUs / replicas | 2 |
| Concurrency | 16 (8 per replica) |
| Documents | 50 |
| Spec hash | 6af67d4c… |
| **Time** |  |
| Wall (busy) | 85.99 s |
| GPU seconds | 86.55 s |
| Cold boot | 0.31 s |
| **Cost** |  |
| Busy-window GPU $ | $0.038220 |
| Billed GPU $ | $0.038467 |
| Billed seconds | 86.55 s |
| Idle $ | $0.016464 (37.05 s) |
| Cost per document | $0.000769 |
| Cost per ok document | $0.000769 |
| Cost per 1M tokens | $0.2073 |
| **Tokens** |  |
| Prompt tokens | 165,315 |
| Completion tokens | 20,229 (10.9%) |
| Total tokens | 185,544 |
| Tokens per document | 3,711 |
| Per document: instructions + template | 2,710 (73.0%) |
| Per document: document text | 597 (16.1%) |
| Per document: output | 405 (10.9%) |
| Instruction tokens per model call | 2,710 over 50 calls |
| Token split basis | fit across documents, 4.47 chars/token |
| Completion p95 / max (ok docs) | 646 / 1,404 |
| **Throughput** |  |
| Tokens / second | 2,157.6 |
| Tokens / second per L4 | 1,078.8 |
| Documents / minute | 34.89 |
| **Latency (per document, ok rows)** |  |
| Mean | 15.66 s |
| p50 | 14.41 s |
| p95 | 22.50 s |
| Max | 40.28 s |
| **Engine (vLLM /metrics)** |  |
| Parallelism (Σ latency ÷ wall) | 9.11× of 16 |
| Slot occupancy | 56.9% |
| Coverage | replicas observed: 2 of 2 |
| Requests per replica (this run) | 21 / 29 |
| Mean TTFT per replica | 1.325 s / 1.339 s |
| Prefix-cache hit per replica | 56.9% / 57.6% |
| Preemptions per replica (this run) | 0 / 0 |
| Length-capped finishes per replica (this run) | 0 / 0 |
| **GPU hardware (nvidia-smi)** | 27 samples · serving-replica nvidia-smi |
| GPU utilization | 76.3 % mean (p95 100.0 / peak 100.0 / min 0.0) |
| Sampling coverage | 100.0 % |
| GPU power draw | 62.9 W (min 33.0 / max 72.5) of 72 W cap |
| GPU memory bandwidth | 69.0 % (min 0.0 / max 100.0) |
| GPU SM clock | 1,524 MHz (min 1,050 / max 2,040) |
| GPU temperature | 69.8 C (min 60.0 / max 76.0) |
| GPU memory used | 19,993 MiB (min 19,992 / max 19,996) |
| **Quality** |  |
| Overall extraction score | 0.6681 (sd 0.063) |
| Score min / max | 0.5663 / 0.8098 |
| Scoring method | `suite` |
| Schema-valid rate | 0.24 |
| Parse errors | 0 |
| Errors | 0 / 50 |

## Figure

![Insurance Claims run dashboard](sand42-50-insurance-claims-specialist-awq-2l4-c16.card.png)

## Per-document results

| # | Document | OK | Score | Latency (s) | Prompt tok | Completion tok | Error |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `DOC-968c9605eab0a87d` | yes | 0.6442 | 13.8 | 2942 | 350 | — |
| 2 | `DOC-2aea7f6dc44b37e1` | yes | 0.7741 | 13.8 | 2835 | 356 | — |
| 3 | `DOC-9ba0a3d4c680b976` | yes | 0.6398 | 13.8 | 2982 | 334 | — |
| 4 | `DOC-2a33a6c34834e769` | yes | 0.6298 | 13.8 | 2953 | 341 | — |
| 5 | `DOC-629fb5789dfd10ca` | yes | 0.7979 | 13.8 | 2836 | 357 | — |
| 6 | `DOC-e7c196f508907c6f` | yes | 0.7830 | 13.8 | 2834 | 362 | — |
| 7 | `DOC-2a55a2b5324659f8` | yes | 0.8098 | 13.8 | 2865 | 347 | — |
| 8 | `DOC-997823d9605a4a59` | yes | 0.6442 | 13.8 | 2973 | 359 | — |
| 9 | `DOC-158c0b74df673b81` | yes | 0.6442 | 13.8 | 2939 | 367 | — |
| 10 | `DOC-991cb72cb83c7a6c` | yes | 0.6442 | 13.8 | 2941 | 367 | — |
| 11 | `DOC-9a6f58879fcb3367` | yes | 0.6487 | 14.1 | 2946 | 371 | — |
| 12 | `DOC-e2a58ed4c02470c0` | yes | 0.7956 | 14.5 | 2835 | 373 | — |
| 13 | `DOC-ef79520b2f50217b` | yes | 0.6915 | 14.9 | 3138 | 378 | — |
| 14 | `DOC-2435c398b95844bc` | yes | 0.6956 | 15.1 | 3080 | 390 | — |
| 15 | `DOC-5c4e70db54374e72` | yes | 0.6874 | 18.4 | 3151 | 403 | — |
| 16 | `DOC-728d06b610b25244` | yes | 0.7043 | 8.5 | 2804 | 289 | — |
| 17 | `DOC-6f6fc9762418a70f` | yes | 0.7048 | 8.4 | 2811 | 294 | — |
| 18 | `DOC-5b1e8e2aed95c089` | yes | 0.6825 | 22.5 | 3123 | 541 | — |
| 19 | `DOC-2d7cc160b78a69c5` | yes | 0.6442 | 11.1 | 2979 | 405 | — |
| 20 | `DOC-00d28a1df0e3f6ba` | yes | 0.6971 | 12.3 | 2812 | 259 | — |
| 21 | `DOC-f5e6c0de5f1d8593` | yes | 0.6283 | 13.3 | 2812 | 280 | — |
| 22 | `DOC-00ccdcb0154a8629` | yes | 0.6228 | 13.4 | 2812 | 285 | — |
| 23 | `DOC-cbfcdb6f42cf2ae6` | yes | 0.6205 | 13.6 | 2806 | 290 | — |
| 24 | `DOC-c34baab0b5fe378a` | yes | 0.6232 | 13.7 | 2807 | 292 | — |
| 25 | `DOC-5060222215c75aa6` | yes | 0.7412 | 13.7 | 2801 | 296 | — |
| 26 | `DOC-87c0c53132830a6c` | yes | 0.6131 | 11.3 | 2993 | 372 | — |
| 27 | `DOC-9051d4cf8d7ab452` | yes | 0.7248 | 16.1 | 3115 | 355 | — |
| 28 | `DOC-29e384939c31d44a` | yes | 0.6131 | 16.7 | 3010 | 365 | — |
| 29 | `DOC-d8df43ed4d8faf89` | yes | 0.7137 | 19.1 | 3107 | 395 | — |
| 30 | `DOC-e4b1466ee8d1ff19` | yes | 0.7037 | 19.2 | 3113 | 401 | — |
| 31 | `DOC-364435343e0a2250` | yes | 0.6474 | 13.9 | 3020 | 393 | — |
| 32 | `DOC-0cdb706a0cdbe3b6` | yes | 0.6131 | 14.4 | 2981 | 315 | — |
| 33 | `DOC-4e21681f375a247d` | yes | 0.6188 | 16.8 | 2985 | 368 | — |
| 34 | `DOC-27b23fd94cc70d9d` | yes | 0.5785 | 15.1 | 2890 | 354 | — |
| 35 | `DOC-3ae2dc5d624e2120` | yes | 0.5999 | 15.4 | 2871 | 347 | — |
| 36 | `DOC-44bcd388c4710b71` | yes | 0.5663 | 14.2 | 2884 | 335 | — |
| 37 | `DOC-93c8d133c296d536` | yes | 0.5796 | 15.0 | 2879 | 356 | — |
| 38 | `DOC-91da307f80433ae3` | yes | 0.5796 | 15.9 | 2894 | 344 | — |
| 39 | `DOC-90338506fc792f32` | yes | 0.5796 | 15.6 | 2882 | 342 | — |
| 40 | `DOC-164aa748f84cef54` | yes | 0.5810 | 15.7 | 2911 | 394 | — |
| 41 | `DOC-7bd9dbc1b39ad41d` | yes | 0.6081 | 28.2 | 3171 | 646 | — |
| 42 | `DOC-7f1f866b022cee63` | yes | 0.7309 | 18.3 | 4985 | 508 | — |
| 43 | `DOC-ab18f15b7a51f1ab` | yes | 0.7427 | 15.6 | 5538 | 423 | — |
| 44 | `DOC-73d64bbeb296bd95` | yes | 0.6198 | 20.6 | 4524 | 542 | — |
| 45 | `DOC-384665a051d0fcd6` | yes | 0.7000 | 17.5 | 5208 | 508 | — |
| 46 | `DOC-1076ac5b4b0df386` | yes | 0.6569 | 14.1 | 4482 | 429 | — |
| 47 | `DOC-85314478b81710d9` | yes | 0.6998 | 14.4 | 5285 | 438 | — |
| 48 | `DOC-6dcc0b9ba494c25b` | yes | 0.7569 | 15.8 | 5114 | 555 | — |
| 49 | `DOC-5b97ae3f8558703c` | yes | 0.6916 | 18.2 | 4565 | 654 | — |
| 50 | `DOC-02f77aa77391a8c2` | yes | 0.6864 | 40.3 | 5091 | 1404 | — |

_Generated 2026-10-12T06:52:18+00:00 by `sandbox run card`. Machine-readable twin: `sand42-50-insurance-claims-specialist-awq-2l4-c16.card.json`._
