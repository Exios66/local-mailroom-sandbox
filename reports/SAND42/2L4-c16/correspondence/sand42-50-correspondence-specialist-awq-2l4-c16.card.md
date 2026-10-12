# Correspondence — 2× L4 · C16 · n=50

**Run:** `sand42-50-correspondence-specialist-awq-2l4-c16` · **Model:** Qwen/Qwen3-8B-AWQ · vLLM v0.29.0 · Modal `sandbox-vllm-b` · L4 @ $0.80/GPU-hr

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
| Run ID | `sand42-50-correspondence-specialist-awq-2l4-c16` |
| GPUs / replicas | 2 |
| Concurrency | 16 (8 per replica) |
| Documents | 50 |
| Spec hash | a779625f… |
| **Time** |  |
| Wall (busy) | 39.89 s |
| GPU seconds | 40.45 s |
| Cold boot | 0.30 s |
| **Cost** |  |
| Busy-window GPU $ | $0.017731 |
| Billed GPU $ | $0.017977 |
| Billed seconds | 40.45 s |
| Idle $ | $0.007696 (17.32 s) |
| Cost per document | $0.000360 |
| Cost per ok document | $0.000360 |
| Cost per 1M tokens | $0.1311 |
| **Tokens** |  |
| Prompt tokens | 129,444 |
| Completion tokens | 7,712 (5.6%) |
| Total tokens | 137,156 |
| Tokens per document | 2,743 |
| Per document: instructions + template | 2,241 (81.7%) |
| Per document: document text | 348 (12.7%) |
| Per document: output | 154 (5.6%) |
| Instruction tokens per model call | 2,241 over 50 calls |
| Token split basis | fit across documents, 4.38 chars/token |
| Completion p95 / max (ok docs) | 204 / 274 |
| **Throughput** |  |
| Tokens / second | 3,438.0 |
| Tokens / second per L4 | 1,719.0 |
| Documents / minute | 75.20 |
| **Latency (per document, ok rows)** |  |
| Mean | 7.23 s |
| p50 | 6.66 s |
| p95 | 10.78 s |
| Max | 11.92 s |
| **Engine (vLLM /metrics)** |  |
| Parallelism (Σ latency ÷ wall) | 9.06× of 16 |
| Slot occupancy | 56.6% |
| Coverage | replicas observed: 2 of 2 |
| Requests per replica (this run) | 29 / 21 |
| Mean TTFT per replica | 1.300 s / 0.774 s |
| Prefix-cache hit per replica | 61.3% / 63.6% |
| Preemptions per replica (this run) | 0 / 0 |
| Length-capped finishes per replica (this run) | 0 / 0 |
| **GPU hardware (nvidia-smi)** | 12 samples · serving-replica nvidia-smi |
| GPU utilization | 63.7 % mean (p95 98.0 / peak 100.0 / min 0.0) |
| Sampling coverage | 95.6 % |
| GPU power draw | 56.8 W (min 29.8 / max 73.2) of 72 W cap |
| GPU memory bandwidth | 57.8 % (min 0.0 / max 100.0) |
| GPU SM clock | 1,624 MHz (min 990 / max 2,040) |
| GPU temperature | 62.3 C (min 54.0 / max 70.0) |
| GPU memory used | 19,973 MiB (min 19,760 / max 19,992) |
| **Quality** |  |
| Overall extraction score | 0.3816 (sd 0.237) |
| Score min / max | 0.0278 / 0.8148 |
| Scoring method | `suite` |
| Schema-valid rate | 1.00 |
| Parse errors | 0 |
| Errors | 0 / 50 |

## Figure

![Correspondence run dashboard](sand42-50-correspondence-specialist-awq-2l4-c16.card.png)

## Per-document results

| # | Document | OK | Score | Latency (s) | Prompt tok | Completion tok | Error |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `DOC-3433644b29e318b3` | yes | 0.4967 | 6.7 | 2311 | 122 | — |
| 2 | `DOC-3c85eb56a4145e0c` | yes | 0.7143 | 6.7 | 2357 | 134 | — |
| 3 | `DOC-a21b03af9a6afc21` | yes | 0.7368 | 6.7 | 2412 | 118 | — |
| 4 | `DOC-2a7acfac00e67bac` | yes | 0.0278 | 8.5 | 2256 | 120 | — |
| 5 | `DOC-fc6108235411ca8e` | yes | 0.0606 | 8.5 | 2465 | 198 | — |
| 6 | `DOC-bcc74152bde91996` | yes | 0.8095 | 8.5 | 2211 | 121 | — |
| 7 | `DOC-c71d3ca0b727a0d4` | yes | 0.3333 | 8.5 | 2310 | 128 | — |
| 8 | `DOC-fcab49d5955c76c0` | yes | 0.0606 | 9.5 | 2332 | 146 | — |
| 9 | `DOC-275198e372250586` | yes | 0.1587 | 9.5 | 2880 | 150 | — |
| 10 | `DOC-0dfd9710f2380220` | yes | 0.2050 | 9.8 | 2367 | 158 | — |
| 11 | `DOC-8ca6802d3a0f5d1a` | yes | 0.8148 | 10.1 | 3289 | 163 | — |
| 12 | `DOC-d9937f535b7c22f3` | yes | 0.6667 | 10.5 | 2447 | 169 | — |
| 13 | `DOC-1de496e8c9350155` | yes | 0.3696 | 10.7 | 2314 | 172 | — |
| 14 | `DOC-af2b2b54e31214cc` | yes | 0.3636 | 10.8 | 2822 | 177 | — |
| 15 | `DOC-b7f699fd18d0f80c` | yes | 0.5185 | 10.8 | 2731 | 178 | — |
| 16 | `DOC-3a21b2695c19d388` | yes | 0.0952 | 11.9 | 2766 | 198 | — |
| 17 | `DOC-ede2172372d1f296` | yes | 0.1111 | 5.5 | 2282 | 136 | — |
| 18 | `DOC-5cdfee2b0ef0a218` | yes | 0.5362 | 6.6 | 2263 | 156 | — |
| 19 | `DOC-e7b6158bfb232964` | yes | 0.5000 | 5.2 | 2246 | 115 | — |
| 20 | `DOC-6bdc0c7c153547b6` | yes | 0.7451 | 7.2 | 2480 | 196 | — |
| 21 | `DOC-25958c023112a96e` | yes | 0.3333 | 5.7 | 2242 | 126 | — |
| 22 | `DOC-8674660f9ccc8243` | yes | 0.5362 | 5.3 | 2377 | 137 | — |
| 23 | `DOC-4ea9a8cde42f450b` | yes | 0.4667 | 5.8 | 2309 | 147 | — |
| 24 | `DOC-38a7cb4be93dbecd` | yes | 0.7778 | 6.7 | 2625 | 159 | — |
| 25 | `DOC-ba3217c0524a9577` | yes | 0.3333 | 4.8 | 2368 | 124 | — |
| 26 | `DOC-4fa7aa63b169fea8` | yes | 0.3333 | 5.9 | 2523 | 142 | — |
| 27 | `DOC-5cef7d1205cc37d5` | yes | 0.4722 | 5.9 | 2581 | 137 | — |
| 28 | `DOC-b78953fa896bdeb9` | yes | 0.5754 | 7.1 | 2441 | 174 | — |
| 29 | `DOC-9417d989cb45b287` | yes | 0.0556 | 4.0 | 2212 | 89 | — |
| 30 | `DOC-3fd5fb2e4b505b04` | yes | 0.7647 | 7.1 | 2584 | 177 | — |
| 31 | `DOC-80c4ee15e95f8cc6` | yes | 0.0494 | 6.9 | 2631 | 168 | — |
| 32 | `DOC-bdf1d75db5874068` | yes | 0.7778 | 10.6 | 2839 | 274 | — |
| 33 | `DOC-65c30d7452215c4b` | yes | 0.1333 | 5.1 | 2272 | 131 | — |
| 34 | `DOC-315b7ca63910e311` | yes | 0.1939 | 8.8 | 2607 | 231 | — |
| 35 | `DOC-a7e5e24fade86aae` | yes | 0.4545 | 6.6 | 3230 | 150 | — |
| 36 | `DOC-fe0e62a4596a649b` | yes | 0.0606 | 5.5 | 2255 | 132 | — |
| 37 | `DOC-8b2609c15d1d37af` | yes | 0.4286 | 9.5 | 2604 | 204 | — |
| 38 | `DOC-44dd971367dd458a` | yes | 0.5889 | 6.2 | 2298 | 111 | — |
| 39 | `DOC-537e1f953940c39c` | yes | 0.2333 | 8.2 | 2600 | 172 | — |
| 40 | `DOC-20dc95a39ec83250` | yes | 0.1911 | 6.4 | 2422 | 168 | — |
| 41 | `DOC-5feb4a34e13ce77a` | yes | 0.1000 | 6.5 | 2415 | 176 | — |
| 42 | `DOC-f64e409a607594bb` | yes | 0.1768 | 4.1 | 2264 | 115 | — |
| 43 | `DOC-aff14c55ba2c4d16` | yes | 0.0769 | 7.3 | 3394 | 150 | — |
| 44 | `DOC-62d410af6bdd29f8` | yes | 0.2286 | 5.1 | 2520 | 146 | — |
| 45 | `DOC-c4074ed5b08f097e` | yes | 0.3827 | 5.5 | 2255 | 128 | — |
| 46 | `DOC-851611e86c9e36d0` | yes | 0.5146 | 4.2 | 2806 | 131 | — |
| 47 | `DOC-90326221a1667d50` | yes | 0.3333 | 7.0 | 3495 | 163 | — |
| 48 | `DOC-f8fb6b01de0fc173` | yes | 0.5278 | 5.4 | 3169 | 142 | — |
| 49 | `DOC-e1e0cc74e784a403` | yes | 0.3212 | 5.3 | 2677 | 191 | — |
| 50 | `DOC-6823b2f649cf1d0a` | yes | 0.3333 | 6.4 | 4888 | 162 | — |

_Generated 2026-10-12T17:17:19+00:00 by `sandbox run card`. Machine-readable twin: `sand42-50-correspondence-specialist-awq-2l4-c16.card.json`._
