# Correspondence — 1× L4 · C8 · n=50

**Run:** `sand42-50-correspondence-specialist-awq-1l4-c8` · **Model:** Qwen/Qwen3-8B-AWQ · vLLM v0.29.0 · Modal `sandbox-vllm` · L4 @ $0.80/GPU-hr

## Conditions

| Condition | Value |
| --- | --- |
| Task | correspondence_specialist |
| Prompt | correspondence_specialist_simplified |
| Temperature | 0.1 (vendored call site) |
| Output cap (max_tokens) | 8,192 |
| Input cap (max_input_chars) | 12,000 |
| Job retries | 2 |
| Dataset | Lucius-Morningstar/mailroom-dataset ground_truth @ ed7576b6, split=all, seed 42 |
| Draw | 50 docs (fingerprint a00ba5dc0159) |
| Engine | awq_marlin · fp8 KV · CUDA graphs [1, 2, 4, 8, 16] · prefix caching on · thinking off |
| Admission | max_model_len 32768 · max_num_seqs 16 per replica · max_inputs 32 |

## Score & cost card

| Metric | Value |
| --- | ---: |
| **Run** |  |
| Run ID | `sand42-50-correspondence-specialist-awq-1l4-c8` |
| GPUs / replicas | 1 |
| Concurrency | 8 (8 per replica) |
| Documents | 50 |
| Spec hash | b0650f19… |
| **Time** |  |
| Wall (busy) | 38.13 s |
| GPU seconds | 60.05 s |
| Cold boot | 0.38 s |
| **Cost** |  |
| Busy-window GPU $ | $0.008473 |
| Billed GPU $ | $0.013344 |
| Billed seconds | 60.05 s |
| Idle $ | not captured |
| Cost per document | $0.000267 |
| Cost per ok document | $0.000267 |
| Cost per 1M tokens | $0.0973 |
| **Tokens** |  |
| Prompt tokens | 129,444 |
| Completion tokens | 7,682 (5.6%) |
| Total tokens | 137,126 |
| Tokens per document | 2,743 |
| Per document: instructions + template | 2,241 (81.7%) |
| Per document: document text | 348 (12.7%) |
| Per document: output | 154 (5.6%) |
| Instruction tokens per model call | 2,241 over 50 calls |
| Token split basis | fit across documents, 4.38 chars/token |
| Completion p95 / max (ok docs) | 200 / 214 |
| **Throughput** |  |
| Tokens / second | 3,596.5 |
| Tokens / second per L4 | 3,596.5 |
| Documents / minute | 78.68 |
| **Latency (per document, ok rows)** |  |
| Mean | 6.55 s |
| p50 | 6.31 s |
| p95 | 8.94 s |
| Max | 9.29 s |
| **Engine (vLLM /metrics)** |  |
| Parallelism (Σ latency ÷ wall) | 8.59× of 8 |
| Slot occupancy | 107.3% |
| Coverage | replicas observed: 1 of 1 |
| Requests per replica (this run) | 50 |
| Mean TTFT per replica | 0.716 s |
| Prefix-cache hit per replica | 63.6% |
| Preemptions per replica (this run) | 0 |
| Length-capped finishes per replica (this run) | 0 |
| **GPU hardware (nvidia-smi)** | 8 samples · serving-replica nvidia-smi |
| GPU utilization | 73.8 % mean (p95 99.0 / peak 99.0 / min 0.0) |
| Sampling coverage | 96.6 % |
| GPU power draw | 63.3 W (min 29.0 / max 72.8) |
| GPU temperature | 51.6 C (min 43.0 / max 57.0) |
| GPU memory used | 20,994 MiB (min 20,791 / max 21,023) |
| **Quality** |  |
| Overall extraction score | 0.3842 (sd 0.246) |
| Score min / max | 0.0278 / 0.9000 |
| Scoring method | `suite` |
| Schema-valid rate | 1.00 |
| Parse errors | 0 |
| Errors | 0 / 50 |

## Per-document results

| # | Document | OK | Score | Latency (s) | Prompt tok | Completion tok | Error |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `DOC-2a7acfac00e67bac` | yes | 0.0278 | 6.5 | 2256 | 120 | — |
| 2 | `DOC-fcab49d5955c76c0` | yes | 0.0606 | 6.5 | 2332 | 136 | — |
| 3 | `DOC-3c85eb56a4145e0c` | yes | 0.7143 | 6.5 | 2357 | 125 | — |
| 4 | `DOC-a21b03af9a6afc21` | yes | 0.8246 | 6.5 | 2412 | 130 | — |
| 5 | `DOC-0dfd9710f2380220` | yes | 0.2050 | 7.1 | 2367 | 164 | — |
| 6 | `DOC-d9937f535b7c22f3` | yes | 0.3333 | 8.8 | 2447 | 179 | — |
| 7 | `DOC-fc6108235411ca8e` | yes | 0.0606 | 9.2 | 2465 | 198 | — |
| 8 | `DOC-3a21b2695c19d388` | yes | 0.1212 | 9.3 | 2766 | 200 | — |
| 9 | `DOC-3433644b29e318b3` | yes | 0.4967 | 5.9 | 2311 | 123 | — |
| 10 | `DOC-1de496e8c9350155` | yes | 0.3696 | 6.0 | 2314 | 131 | — |
| 11 | `DOC-275198e372250586` | yes | 0.1587 | 6.2 | 2880 | 150 | — |
| 12 | `DOC-c71d3ca0b727a0d4` | yes | 0.3333 | 4.9 | 2310 | 128 | — |
| 13 | `DOC-bcc74152bde91996` | yes | 0.8095 | 4.7 | 2211 | 121 | — |
| 14 | `DOC-af2b2b54e31214cc` | yes | 0.3636 | 7.9 | 2822 | 175 | — |
| 15 | `DOC-b7f699fd18d0f80c` | yes | 0.5185 | 8.9 | 2731 | 189 | — |
| 16 | `DOC-8ca6802d3a0f5d1a` | yes | 0.8148 | 6.6 | 3289 | 163 | — |
| 17 | `DOC-ede2172372d1f296` | yes | 0.1111 | 5.3 | 2282 | 140 | — |
| 18 | `DOC-5cdfee2b0ef0a218` | yes | 0.5362 | 6.2 | 2263 | 156 | — |
| 19 | `DOC-e7b6158bfb232964` | yes | 0.5000 | 4.3 | 2246 | 117 | — |
| 20 | `DOC-38a7cb4be93dbecd` | yes | 0.7778 | 5.6 | 2625 | 159 | — |
| 21 | `DOC-25958c023112a96e` | yes | 0.6667 | 6.3 | 2242 | 172 | — |
| 22 | `DOC-bdf1d75db5874068` | yes | 0.7778 | 6.0 | 2839 | 166 | — |
| 23 | `DOC-6bdc0c7c153547b6` | yes | 0.6147 | 7.7 | 2480 | 198 | — |
| 24 | `DOC-4fa7aa63b169fea8` | yes | 0.3333 | 6.1 | 2523 | 150 | — |
| 25 | `DOC-8674660f9ccc8243` | yes | 0.5362 | 5.9 | 2377 | 142 | — |
| 26 | `DOC-ba3217c0524a9577` | yes | 0.3333 | 4.9 | 2368 | 124 | — |
| 27 | `DOC-4ea9a8cde42f450b` | yes | 0.4667 | 6.3 | 2309 | 156 | — |
| 28 | `DOC-5cef7d1205cc37d5` | yes | 0.2341 | 5.2 | 2581 | 137 | — |
| 29 | `DOC-b78953fa896bdeb9` | yes | 0.5754 | 7.4 | 2441 | 169 | — |
| 30 | `DOC-3fd5fb2e4b505b04` | yes | 0.7647 | 7.5 | 2584 | 184 | — |
| 31 | `DOC-315b7ca63910e311` | yes | 0.1939 | 8.9 | 2607 | 214 | — |
| 32 | `DOC-9417d989cb45b287` | yes | 0.0556 | 4.2 | 2212 | 89 | — |
| 33 | `DOC-8b2609c15d1d37af` | yes | 0.4286 | 8.4 | 2604 | 213 | — |
| 34 | `DOC-80c4ee15e95f8cc6` | yes | 0.0494 | 7.0 | 2631 | 159 | — |
| 35 | `DOC-a7e5e24fade86aae` | yes | 0.4545 | 6.8 | 3230 | 158 | — |
| 36 | `DOC-537e1f953940c39c` | yes | 0.2333 | 7.2 | 2600 | 172 | — |
| 37 | `DOC-65c30d7452215c4b` | yes | 0.1333 | 5.0 | 2272 | 131 | — |
| 38 | `DOC-aff14c55ba2c4d16` | yes | 0.0769 | 6.6 | 3394 | 150 | — |
| 39 | `DOC-44dd971367dd458a` | yes | 0.9000 | 5.5 | 2298 | 130 | — |
| 40 | `DOC-fe0e62a4596a649b` | yes | 0.0606 | 5.6 | 2255 | 132 | — |
| 41 | `DOC-20dc95a39ec83250` | yes | 0.1911 | 7.7 | 2422 | 167 | — |
| 42 | `DOC-c4074ed5b08f097e` | yes | 0.3827 | 6.2 | 2255 | 132 | — |
| 43 | `DOC-90326221a1667d50` | yes | 0.3333 | 7.8 | 3495 | 152 | — |
| 44 | `DOC-f64e409a607594bb` | yes | 0.1768 | 5.5 | 2264 | 108 | — |
| 45 | `DOC-5feb4a34e13ce77a` | yes | 0.1000 | 8.4 | 2415 | 174 | — |
| 46 | `DOC-62d410af6bdd29f8` | yes | 0.2286 | 8.5 | 2520 | 192 | — |
| 47 | `DOC-851611e86c9e36d0` | yes | 0.5146 | 5.8 | 2806 | 141 | — |
| 48 | `DOC-6823b2f649cf1d0a` | yes | 0.4074 | 6.3 | 4888 | 143 | — |
| 49 | `DOC-f8fb6b01de0fc173` | yes | 0.5278 | 4.6 | 3169 | 142 | — |
| 50 | `DOC-e1e0cc74e784a403` | yes | 0.3212 | 5.2 | 2677 | 181 | — |

_Generated 2026-10-12T02:59:04+00:00 by `sandbox run card`. Machine-readable twin: `sand42-50-correspondence-specialist-awq-1l4-c8.card.json`._
