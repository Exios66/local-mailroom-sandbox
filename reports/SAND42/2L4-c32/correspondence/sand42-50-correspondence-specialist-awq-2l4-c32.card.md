# Correspondence — 2× L4 · C32 · n=50

**Run:** `sand42-50-correspondence-specialist-awq-2l4-c32` · **Model:** Qwen/Qwen3-8B-AWQ · vLLM v0.29.0 · Modal `sandbox-vllm` · L4 @ $0.80/GPU-hr

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
| Run ID | `sand42-50-correspondence-specialist-awq-2l4-c32` |
| GPUs / replicas | 2 |
| Concurrency | 32 (16 per replica) |
| Documents | 50 |
| Spec hash | 6309643e… |
| **Time** |  |
| Wall (busy) | 39.05 s |
| GPU seconds | 39.68 s |
| Cold boot | 0.24 s |
| **Cost** |  |
| Busy-window GPU $ | $0.017357 |
| Billed GPU $ | $0.017634 |
| Billed seconds | 39.68 s |
| Idle $ | $0.008246 (18.55 s) |
| Cost per document | $0.000353 |
| Cost per ok document | $0.000353 |
| Cost per 1M tokens | $0.1285 |
| **Tokens** |  |
| Prompt tokens | 129,444 |
| Completion tokens | 7,747 (5.6%) |
| Total tokens | 137,191 |
| Tokens per document | 2,744 |
| Per document: instructions + template | 2,241 (81.7%) |
| Per document: document text | 348 (12.7%) |
| Per document: output | 155 (5.6%) |
| Instruction tokens per model call | 2,241 over 50 calls |
| Token split basis | fit across documents, 4.38 chars/token |
| Completion p95 / max (ok docs) | 223 / 231 |
| **Throughput** |  |
| Tokens / second | 3,512.9 |
| Tokens / second per L4 | 1,756.5 |
| Documents / minute | 76.82 |
| **Latency (per document, ok rows)** |  |
| Mean | 13.12 s |
| p50 | 12.86 s |
| p95 | 22.27 s |
| Max | 23.52 s |
| **Engine (vLLM /metrics)** |  |
| Parallelism (Σ latency ÷ wall) | 16.80× of 32 |
| Slot occupancy | 52.5% |
| Coverage | replicas observed: 2 of 2 |
| Requests per replica (this run) | 39 / 11 |
| Mean TTFT per replica | 6.147 s / 0.629 s |
| Prefix-cache hit per replica | 62.7% / 60.7% |
| Preemptions per replica (this run) | 0 / 0 |
| Length-capped finishes per replica (this run) | 0 / 0 |
| **GPU hardware (nvidia-smi)** | 11 samples · serving-replica nvidia-smi |
| GPU utilization | 62.3 % mean (p95 100.0 / peak 100.0 / min 0.0) |
| Sampling coverage | 100.0 % |
| GPU power draw | 57.2 W (min 30.2 / max 72.7) of 72 W cap |
| GPU memory bandwidth | 54.5 % (min 0.0 / max 100.0) |
| GPU SM clock | 1,670 MHz (min 1,140 / max 2,040) |
| GPU temperature | 67.5 C (min 60.0 / max 71.0) |
| GPU memory used | 20,981 MiB (min 20,790 / max 21,024) |
| **Quality** |  |
| Overall extraction score | 0.3775 (sd 0.236) |
| Score min / max | 0.0278 / 0.8246 |
| Scoring method | `suite` |
| Schema-valid rate | 1.00 |
| Parse errors | 0 |
| Errors | 0 / 50 |

## Figure

![Correspondence run dashboard](sand42-50-correspondence-specialist-awq-2l4-c32.card.png)

## Per-document results

| # | Document | OK | Score | Latency (s) | Prompt tok | Completion tok | Error |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `DOC-c71d3ca0b727a0d4` | yes | 0.3333 | 6.3 | 2310 | 128 | — |
| 2 | `DOC-25958c023112a96e` | yes | 0.6667 | 6.7 | 2242 | 170 | — |
| 3 | `DOC-e7b6158bfb232964` | yes | 0.5000 | 8.6 | 2246 | 115 | — |
| 4 | `DOC-1de496e8c9350155` | yes | 0.3696 | 8.7 | 2314 | 115 | — |
| 5 | `DOC-2a7acfac00e67bac` | yes | 0.0278 | 8.9 | 2256 | 120 | — |
| 6 | `DOC-bcc74152bde91996` | yes | 0.8095 | 9.3 | 2211 | 121 | — |
| 7 | `DOC-ba3217c0524a9577` | yes | 0.3333 | 9.9 | 2368 | 124 | — |
| 8 | `DOC-3433644b29e318b3` | yes | 0.4967 | 10.0 | 2311 | 123 | — |
| 9 | `DOC-3c85eb56a4145e0c` | yes | 0.7143 | 10.9 | 2357 | 134 | — |
| 10 | `DOC-5cef7d1205cc37d5` | yes | 0.2341 | 11.0 | 2581 | 137 | — |
| 11 | `DOC-8674660f9ccc8243` | yes | 0.5362 | 11.5 | 2377 | 142 | — |
| 12 | `DOC-80c4ee15e95f8cc6` | yes | 0.0494 | 5.7 | 2631 | 166 | — |
| 13 | `DOC-8ca6802d3a0f5d1a` | yes | 0.8148 | 12.2 | 3289 | 153 | — |
| 14 | `DOC-5cdfee2b0ef0a218` | yes | 0.5362 | 12.2 | 2263 | 156 | — |
| 15 | `DOC-0dfd9710f2380220` | yes | 0.2050 | 12.8 | 2367 | 156 | — |
| 16 | `DOC-d9937f535b7c22f3` | yes | 0.3333 | 13.4 | 2447 | 171 | — |
| 17 | `DOC-65c30d7452215c4b` | yes | 0.1333 | 4.8 | 2272 | 131 | — |
| 18 | `DOC-b7f699fd18d0f80c` | yes | 0.5185 | 14.2 | 2731 | 189 | — |
| 19 | `DOC-44dd971367dd458a` | yes | 0.6222 | 4.3 | 2298 | 113 | — |
| 20 | `DOC-a7e5e24fade86aae` | yes | 0.4545 | 5.9 | 3230 | 152 | — |
| 21 | `DOC-3a21b2695c19d388` | yes | 0.1212 | 14.8 | 2766 | 200 | — |
| 22 | `DOC-315b7ca63910e311` | yes | 0.1939 | 15.4 | 2607 | 223 | — |
| 23 | `DOC-f64e409a607594bb` | yes | 0.1768 | 4.3 | 2264 | 125 | — |
| 24 | `DOC-fcab49d5955c76c0` | yes | 0.0606 | 16.9 | 2332 | 136 | — |
| 25 | `DOC-5feb4a34e13ce77a` | yes | 0.1000 | 6.1 | 2415 | 180 | — |
| 26 | `DOC-275198e372250586` | yes | 0.1587 | 17.7 | 2880 | 150 | — |
| 27 | `DOC-62d410af6bdd29f8` | yes | 0.2286 | 5.9 | 2520 | 182 | — |
| 28 | `DOC-851611e86c9e36d0` | yes | 0.4971 | 4.5 | 2806 | 142 | — |
| 29 | `DOC-a21b03af9a6afc21` | yes | 0.8246 | 18.4 | 2412 | 130 | — |
| 30 | `DOC-b78953fa896bdeb9` | yes | 0.5754 | 18.7 | 2441 | 171 | — |
| 31 | `DOC-e1e0cc74e784a403` | yes | 0.3212 | 5.1 | 2677 | 186 | — |
| 32 | `DOC-bdf1d75db5874068` | yes | 0.7778 | 19.7 | 2839 | 167 | — |
| 33 | `DOC-4ea9a8cde42f450b` | yes | 0.4667 | 19.8 | 2309 | 152 | — |
| 34 | `DOC-3fd5fb2e4b505b04` | yes | 0.7647 | 20.9 | 2584 | 184 | — |
| 35 | `DOC-9417d989cb45b287` | yes | 0.0556 | 12.9 | 2212 | 89 | — |
| 36 | `DOC-ede2172372d1f296` | yes | 0.1111 | 21.6 | 2282 | 140 | — |
| 37 | `DOC-fc6108235411ca8e` | yes | 0.0606 | 21.7 | 2465 | 198 | — |
| 38 | `DOC-af2b2b54e31214cc` | yes | 0.3636 | 21.8 | 2822 | 177 | — |
| 39 | `DOC-8b2609c15d1d37af` | yes | 0.4286 | 21.7 | 2604 | 204 | — |
| 40 | `DOC-4fa7aa63b169fea8` | yes | 0.3333 | 22.3 | 2523 | 142 | — |
| 41 | `DOC-38a7cb4be93dbecd` | yes | 0.7407 | 23.3 | 2625 | 231 | — |
| 42 | `DOC-6bdc0c7c153547b6` | yes | 0.6147 | 23.5 | 2480 | 224 | — |
| 43 | `DOC-537e1f953940c39c` | yes | 0.2333 | 17.0 | 2600 | 181 | — |
| 44 | `DOC-fe0e62a4596a649b` | yes | 0.0606 | 14.1 | 2255 | 132 | — |
| 45 | `DOC-aff14c55ba2c4d16` | yes | 0.0769 | 15.2 | 3394 | 150 | — |
| 46 | `DOC-c4074ed5b08f097e` | yes | 0.3827 | 12.9 | 2255 | 132 | — |
| 47 | `DOC-90326221a1667d50` | yes | 0.3333 | 13.7 | 3495 | 153 | — |
| 48 | `DOC-6823b2f649cf1d0a` | yes | 0.4074 | 12.5 | 4888 | 141 | — |
| 49 | `DOC-f8fb6b01de0fc173` | yes | 0.5278 | 11.7 | 3169 | 142 | — |
| 50 | `DOC-20dc95a39ec83250` | yes | 0.1911 | 14.6 | 2422 | 167 | — |

_Generated 2026-10-12T16:23:18+00:00 by `sandbox run card`. Machine-readable twin: `sand42-50-correspondence-specialist-awq-2l4-c32.card.json`._
