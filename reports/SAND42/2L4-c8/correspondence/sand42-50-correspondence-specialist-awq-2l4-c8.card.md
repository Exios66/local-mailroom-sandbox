# Correspondence — 2× L4 · C8 · n=50

**Run:** `sand42-50-correspondence-specialist-awq-2l4-c8` · **Model:** Qwen/Qwen3-8B-AWQ · vLLM v0.29.0 · Modal `sandbox-vllm` · L4 @ $0.80/GPU-hr

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
| Run ID | `sand42-50-correspondence-specialist-awq-2l4-c8` |
| GPUs / replicas | 2 |
| Concurrency | 8 (4 per replica) |
| Documents | 50 |
| Spec hash | 853a5c1c… |
| **Time** |  |
| Wall (busy) | 50.63 s |
| GPU seconds | 51.87 s |
| Cold boot | 0.32 s |
| **Cost** |  |
| Busy-window GPU $ | $0.022503 |
| Billed GPU $ | $0.023052 |
| Billed seconds | 51.87 s |
| Idle $ | $0.007086 (15.95 s) |
| Cost per document | $0.000461 |
| Cost per ok document | $0.000461 |
| Cost per 1M tokens | $0.1678 |
| **Tokens** |  |
| Prompt tokens | 129,444 |
| Completion tokens | 7,904 (5.8%) |
| Total tokens | 137,348 |
| Tokens per document | 2,747 |
| Per document: instructions + template | 2,241 (81.6%) |
| Per document: document text | 348 (12.7%) |
| Per document: output | 158 (5.8%) |
| Instruction tokens per model call | 2,241 over 50 calls |
| Token split basis | fit across documents, 4.38 chars/token |
| Completion p95 / max (ok docs) | 225 / 274 |
| **Throughput** |  |
| Tokens / second | 2,712.7 |
| Tokens / second per L4 | 1,356.4 |
| Documents / minute | 59.25 |
| **Latency (per document, ok rows)** |  |
| Mean | 5.55 s |
| p50 | 5.43 s |
| p95 | 8.11 s |
| Max | 8.55 s |
| **Engine (vLLM /metrics)** |  |
| Parallelism (Σ latency ÷ wall) | 5.48× of 8 |
| Slot occupancy | 68.5% |
| Coverage | replicas observed: 2 of 2 |
| Requests per replica (this run) | 27 / 23 |
| Mean TTFT per replica | 0.601 s / 0.607 s |
| Prefix-cache hit per replica | 65.0% / 59.4% |
| Preemptions per replica (this run) | 0 / 0 |
| Length-capped finishes per replica (this run) | 0 / 0 |
| **GPU hardware (nvidia-smi)** | 17 samples · serving-replica nvidia-smi |
| GPU utilization | 69.1 % mean (p95 100.0 / peak 100.0 / min 0.0) |
| Sampling coverage | 100.0 % |
| GPU power draw | 61.7 W (min 31.3 / max 73.6) of 72 W cap |
| GPU memory bandwidth | 56.4 % (min 0.0 / max 100.0) |
| GPU SM clock | 1,547 MHz (min 1,020 / max 2,040) |
| GPU temperature | 71.6 C (min 64.0 / max 78.0) |
| GPU memory used | 20,983 MiB (min 20,764 / max 20,998) |
| **Quality** |  |
| Overall extraction score | 0.3792 (sd 0.241) |
| Score min / max | 0.0278 / 0.8246 |
| Scoring method | `suite` |
| Schema-valid rate | 1.00 |
| Parse errors | 0 |
| Errors | 0 / 50 |
| **Paired n** |  |
| Documents a paired delta can use | 50 of 50 |

## Figure

![Correspondence run dashboard](sand42-50-correspondence-specialist-awq-2l4-c8.card.png)

## Per-document results

| # | Document | OK | Score | Latency (s) | Prompt tok | Completion tok | Error |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `DOC-2a7acfac00e67bac` | yes | 0.0278 | 6.3 | 2256 | 120 | — |
| 2 | `DOC-3c85eb56a4145e0c` | yes | 0.7143 | 6.3 | 2357 | 133 | — |
| 3 | `DOC-fcab49d5955c76c0` | yes | 0.0606 | 6.3 | 2332 | 136 | — |
| 4 | `DOC-a21b03af9a6afc21` | yes | 0.8246 | 6.3 | 2412 | 130 | — |
| 5 | `DOC-0dfd9710f2380220` | yes | 0.2050 | 6.6 | 2367 | 158 | — |
| 6 | `DOC-d9937f535b7c22f3` | yes | 0.3333 | 7.3 | 2447 | 173 | — |
| 7 | `DOC-fc6108235411ca8e` | yes | 0.0606 | 8.1 | 2465 | 198 | — |
| 8 | `DOC-3a21b2695c19d388` | yes | 0.1212 | 8.1 | 2766 | 200 | — |
| 9 | `DOC-c71d3ca0b727a0d4` | yes | 0.3333 | 3.7 | 2310 | 128 | — |
| 10 | `DOC-1de496e8c9350155` | yes | 0.3696 | 4.9 | 2314 | 131 | — |
| 11 | `DOC-3433644b29e318b3` | yes | 0.4967 | 5.0 | 2311 | 159 | — |
| 12 | `DOC-bcc74152bde91996` | yes | 0.8095 | 3.3 | 2211 | 121 | — |
| 13 | `DOC-af2b2b54e31214cc` | yes | 0.3636 | 5.8 | 2822 | 178 | — |
| 14 | `DOC-275198e372250586` | yes | 0.1587 | 5.6 | 2880 | 150 | — |
| 15 | `DOC-b7f699fd18d0f80c` | yes | 0.5185 | 7.1 | 2731 | 189 | — |
| 16 | `DOC-8ca6802d3a0f5d1a` | yes | 0.8148 | 5.6 | 3289 | 163 | — |
| 17 | `DOC-ede2172372d1f296` | yes | 0.1111 | 4.5 | 2282 | 140 | — |
| 18 | `DOC-5cdfee2b0ef0a218` | yes | 0.5362 | 4.6 | 2263 | 146 | — |
| 19 | `DOC-25958c023112a96e` | yes | 0.6667 | 5.3 | 2242 | 170 | — |
| 20 | `DOC-e7b6158bfb232964` | yes | 0.5000 | 3.6 | 2246 | 118 | — |
| 21 | `DOC-4fa7aa63b169fea8` | yes | 0.3333 | 4.4 | 2523 | 142 | — |
| 22 | `DOC-6bdc0c7c153547b6` | yes | 0.7451 | 7.1 | 2480 | 225 | — |
| 23 | `DOC-38a7cb4be93dbecd` | yes | 0.7407 | 7.2 | 2625 | 231 | — |
| 24 | `DOC-8674660f9ccc8243` | yes | 0.5362 | 4.4 | 2377 | 142 | — |
| 25 | `DOC-bdf1d75db5874068` | yes | 0.7778 | 8.6 | 2839 | 274 | — |
| 26 | `DOC-4ea9a8cde42f450b` | yes | 0.4667 | 5.2 | 2309 | 152 | — |
| 27 | `DOC-ba3217c0524a9577` | yes | 0.3333 | 4.0 | 2368 | 124 | — |
| 28 | `DOC-b78953fa896bdeb9` | yes | 0.5754 | 6.2 | 2441 | 171 | — |
| 29 | `DOC-5cef7d1205cc37d5` | yes | 0.1667 | 5.4 | 2581 | 145 | — |
| 30 | `DOC-3fd5fb2e4b505b04` | yes | 0.7647 | 5.7 | 2584 | 184 | — |
| 31 | `DOC-a7e5e24fade86aae` | yes | 0.4545 | 5.0 | 3230 | 158 | — |
| 32 | `DOC-80c4ee15e95f8cc6` | yes | 0.0494 | 5.4 | 2631 | 162 | — |
| 33 | `DOC-9417d989cb45b287` | yes | 0.0556 | 3.2 | 2212 | 89 | — |
| 34 | `DOC-537e1f953940c39c` | yes | 0.2333 | 5.4 | 2600 | 172 | — |
| 35 | `DOC-315b7ca63910e311` | yes | 0.1939 | 7.6 | 2607 | 223 | — |
| 36 | `DOC-8b2609c15d1d37af` | yes | 0.4286 | 6.9 | 2604 | 204 | — |
| 37 | `DOC-65c30d7452215c4b` | yes | 0.1333 | 4.7 | 2272 | 129 | — |
| 38 | `DOC-aff14c55ba2c4d16` | yes | 0.0769 | 5.3 | 3394 | 150 | — |
| 39 | `DOC-44dd971367dd458a` | yes | 0.6222 | 4.3 | 2298 | 113 | — |
| 40 | `DOC-fe0e62a4596a649b` | yes | 0.0606 | 4.7 | 2255 | 132 | — |
| 41 | `DOC-20dc95a39ec83250` | yes | 0.1911 | 5.5 | 2422 | 167 | — |
| 42 | `DOC-5feb4a34e13ce77a` | yes | 0.1000 | 5.5 | 2415 | 174 | — |
| 43 | `DOC-62d410af6bdd29f8` | yes | 0.2286 | 6.1 | 2520 | 182 | — |
| 44 | `DOC-f64e409a607594bb` | yes | 0.1768 | 4.2 | 2264 | 125 | — |
| 45 | `DOC-90326221a1667d50` | yes | 0.3333 | 6.6 | 3495 | 157 | — |
| 46 | `DOC-c4074ed5b08f097e` | yes | 0.3827 | 5.3 | 2255 | 129 | — |
| 47 | `DOC-851611e86c9e36d0` | yes | 0.5146 | 4.4 | 2806 | 141 | — |
| 48 | `DOC-6823b2f649cf1d0a` | yes | 0.4074 | 5.5 | 4888 | 143 | — |
| 49 | `DOC-f8fb6b01de0fc173` | yes | 0.5278 | 4.3 | 3169 | 142 | — |
| 50 | `DOC-e1e0cc74e784a403` | yes | 0.3212 | 5.0 | 2677 | 181 | — |

_Generated 2026-10-12T22:59:02+00:00 by `sandbox run card`. Machine-readable twin: `sand42-50-correspondence-specialist-awq-2l4-c8.card.json`._
