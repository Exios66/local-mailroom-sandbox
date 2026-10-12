# Correspondence — 1× L4 · C16 · n=50

**Run:** `sand42-50-correspondence-specialist-awq-1l4-c16` · **Model:** Qwen/Qwen3-8B-AWQ · vLLM v0.29.0 · Modal `sandbox-vllm` · L4 @ $0.80/GPU-hr

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
| Run ID | `sand42-50-correspondence-specialist-awq-1l4-c16` |
| GPUs / replicas | 1 |
| Concurrency | 16 (16 per replica) |
| Documents | 50 |
| Spec hash | 6424743b… |
| **Time** |  |
| Wall (busy) | 47.27 s |
| GPU seconds | 62.95 s |
| Cold boot | 0.32 s |
| **Cost** |  |
| Busy-window GPU $ | $0.010504 |
| Billed GPU $ | $0.013990 |
| Billed seconds | 62.95 s |
| Idle $ | $0.003699 (16.65 s) |
| Cost per document | $0.000280 |
| Cost per ok document | $0.000280 |
| Cost per 1M tokens | $0.1019 |
| **Tokens** |  |
| Prompt tokens | 129,444 |
| Completion tokens | 7,876 (5.7%) |
| Total tokens | 137,320 |
| Tokens per document | 2,746 |
| Per document: instructions + template | 2,241 (81.6%) |
| Per document: document text | 348 (12.7%) |
| Per document: output | 158 (5.7%) |
| Instruction tokens per model call | 2,241 over 50 calls |
| Token split basis | fit across documents, 4.38 chars/token |
| Completion p95 / max (ok docs) | 217 / 340 |
| **Throughput** |  |
| Tokens / second | 2,905.2 |
| Tokens / second per L4 | 2,905.2 |
| Documents / minute | 63.47 |
| **Latency (per document, ok rows)** |  |
| Mean | 9.80 s |
| p50 | 9.37 s |
| p95 | 14.01 s |
| Max | 20.30 s |
| **Engine (vLLM /metrics)** |  |
| Parallelism (Σ latency ÷ wall) | 10.37× of 16 |
| Slot occupancy | 64.8% |
| Coverage | replicas observed: 1 of 1 |
| Requests per replica (this run) | 50 |
| Mean TTFT per replica | 1.417 s |
| Prefix-cache hit per replica | 63.6% |
| Preemptions per replica (this run) | 0 |
| Length-capped finishes per replica (this run) | 0 |
| **GPU hardware (nvidia-smi)** | 11 samples · serving-replica nvidia-smi |
| GPU utilization | 44.4 % mean (p95 100.0 / peak 100.0 / min 0.0) |
| Sampling coverage | 100.0 % |
| GPU power draw | 51.0 W (min 30.7 / max 73.1) of 72 W cap |
| GPU memory bandwidth | 38.9 % (min 0.0 / max 99.0) |
| GPU SM clock | 1,711 MHz (min 1,110 / max 2,040) |
| GPU temperature | 73.6 C (min 65.0 / max 78.0) |
| GPU memory used | 21,002 MiB (min 20,790 / max 21,024) |
| **Quality** |  |
| Overall extraction score | 0.3814 (sd 0.244) |
| Score min / max | 0.0278 / 0.8148 |
| Scoring method | `suite` |
| Schema-valid rate | 1.00 |
| Parse errors | 0 |
| Errors | 0 / 50 |

## Figure

![Correspondence run dashboard](sand42-50-correspondence-specialist-awq-1l4-c16.card.png)

## Per-document results

| # | Document | OK | Score | Latency (s) | Prompt tok | Completion tok | Error |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `DOC-2a7acfac00e67bac` | yes | 0.0278 | 9.4 | 2256 | 120 | — |
| 2 | `DOC-bcc74152bde91996` | yes | 0.8095 | 9.4 | 2211 | 121 | — |
| 3 | `DOC-1de496e8c9350155` | yes | 0.3696 | 9.4 | 2314 | 126 | — |
| 4 | `DOC-c71d3ca0b727a0d4` | yes | 0.3333 | 9.4 | 2310 | 128 | — |
| 5 | `DOC-a21b03af9a6afc21` | yes | 0.7368 | 9.4 | 2412 | 118 | — |
| 6 | `DOC-3c85eb56a4145e0c` | yes | 0.7143 | 9.4 | 2357 | 137 | — |
| 7 | `DOC-fcab49d5955c76c0` | yes | 0.0606 | 9.5 | 2332 | 136 | — |
| 8 | `DOC-3433644b29e318b3` | yes | 0.4967 | 9.6 | 2311 | 143 | — |
| 9 | `DOC-0dfd9710f2380220` | yes | 0.2050 | 11.8 | 2367 | 156 | — |
| 10 | `DOC-275198e372250586` | yes | 0.1587 | 12.0 | 2880 | 160 | — |
| 11 | `DOC-8ca6802d3a0f5d1a` | yes | 0.8148 | 12.1 | 3289 | 168 | — |
| 12 | `DOC-d9937f535b7c22f3` | yes | 0.6667 | 12.2 | 2447 | 171 | — |
| 13 | `DOC-b7f699fd18d0f80c` | yes | 0.5185 | 13.5 | 2731 | 189 | — |
| 14 | `DOC-af2b2b54e31214cc` | yes | 0.3636 | 13.8 | 2822 | 193 | — |
| 15 | `DOC-fc6108235411ca8e` | yes | 0.0606 | 14.0 | 2465 | 198 | — |
| 16 | `DOC-3a21b2695c19d388` | yes | 0.0952 | 14.0 | 2766 | 199 | — |
| 17 | `DOC-e7b6158bfb232964` | yes | 0.5000 | 7.4 | 2246 | 115 | — |
| 18 | `DOC-ede2172372d1f296` | yes | 0.1111 | 8.6 | 2282 | 140 | — |
| 19 | `DOC-4fa7aa63b169fea8` | yes | 0.3333 | 8.4 | 2523 | 143 | — |
| 20 | `DOC-ba3217c0524a9577` | yes | 0.3333 | 6.0 | 2368 | 124 | — |
| 21 | `DOC-5cdfee2b0ef0a218` | yes | 0.5362 | 9.3 | 2263 | 156 | — |
| 22 | `DOC-38a7cb4be93dbecd` | yes | 0.7778 | 10.2 | 2625 | 159 | — |
| 23 | `DOC-8674660f9ccc8243` | yes | 0.5362 | 7.8 | 2377 | 142 | — |
| 24 | `DOC-25958c023112a96e` | yes | 0.6667 | 10.5 | 2242 | 172 | — |
| 25 | `DOC-4ea9a8cde42f450b` | yes | 0.4667 | 8.2 | 2309 | 151 | — |
| 26 | `DOC-5cef7d1205cc37d5` | yes | 0.1667 | 8.4 | 2581 | 145 | — |
| 27 | `DOC-b78953fa896bdeb9` | yes | 0.5754 | 9.8 | 2441 | 170 | — |
| 28 | `DOC-6bdc0c7c153547b6` | yes | 0.7451 | 14.1 | 2480 | 225 | — |
| 29 | `DOC-9417d989cb45b287` | yes | 0.0556 | 6.1 | 2212 | 89 | — |
| 30 | `DOC-3fd5fb2e4b505b04` | yes | 0.7647 | 10.8 | 2584 | 184 | — |
| 31 | `DOC-8b2609c15d1d37af` | yes | 0.4286 | 11.4 | 2604 | 204 | — |
| 32 | `DOC-65c30d7452215c4b` | yes | 0.1333 | 8.2 | 2272 | 129 | — |
| 33 | `DOC-44dd971367dd458a` | yes | 0.6222 | 7.3 | 2298 | 113 | — |
| 34 | `DOC-80c4ee15e95f8cc6` | yes | 0.0494 | 10.2 | 2631 | 160 | — |
| 35 | `DOC-315b7ca63910e311` | yes | 0.1939 | 13.8 | 2607 | 217 | — |
| 36 | `DOC-fe0e62a4596a649b` | yes | 0.0606 | 8.8 | 2255 | 132 | — |
| 37 | `DOC-a7e5e24fade86aae` | yes | 0.4545 | 10.7 | 3230 | 152 | — |
| 38 | `DOC-aff14c55ba2c4d16` | yes | 0.0769 | 9.6 | 3394 | 150 | — |
| 39 | `DOC-537e1f953940c39c` | yes | 0.2333 | 11.3 | 2600 | 168 | — |
| 40 | `DOC-bdf1d75db5874068` | yes | 0.7778 | 20.3 | 2839 | 340 | — |
| 41 | `DOC-20dc95a39ec83250` | yes | 0.1911 | 9.9 | 2422 | 167 | — |
| 42 | `DOC-90326221a1667d50` | yes | 0.3333 | 8.6 | 3495 | 152 | — |
| 43 | `DOC-f64e409a607594bb` | yes | 0.1768 | 6.6 | 2264 | 125 | — |
| 44 | `DOC-5feb4a34e13ce77a` | yes | 0.1000 | 9.3 | 2415 | 180 | — |
| 45 | `DOC-c4074ed5b08f097e` | yes | 0.3827 | 7.3 | 2255 | 132 | — |
| 46 | `DOC-6823b2f649cf1d0a` | yes | 0.4074 | 6.5 | 4888 | 135 | — |
| 47 | `DOC-62d410af6bdd29f8` | yes | 0.2286 | 8.4 | 2520 | 183 | — |
| 48 | `DOC-851611e86c9e36d0` | yes | 0.5146 | 5.6 | 2806 | 141 | — |
| 49 | `DOC-f8fb6b01de0fc173` | yes | 0.5278 | 5.5 | 3169 | 142 | — |
| 50 | `DOC-e1e0cc74e784a403` | yes | 0.1768 | 6.3 | 2677 | 176 | — |

_Generated 2026-10-12T08:00:25+00:00 by `sandbox run card`. Machine-readable twin: `sand42-50-correspondence-specialist-awq-1l4-c16.card.json`._
