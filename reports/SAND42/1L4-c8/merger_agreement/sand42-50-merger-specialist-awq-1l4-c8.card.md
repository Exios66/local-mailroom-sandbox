# Merger Agreements — 1× L4 · C8 · n=50

**Run:** `sand42-50-merger-specialist-awq-1l4-c8` · **Model:** Qwen/Qwen3-8B-AWQ · vLLM v0.29.0 · Modal `sandbox-vllm` · L4 @ $0.80/GPU-hr

## Conditions

| Condition | Value |
| --- | --- |
| Task | merger_agreement_specialist |
| Prompt | merger_agreement_specialist_simplified |
| Temperature | 0.7 (posture knob) |
| Output cap (max_tokens) | 6,144 |
| Input cap (max_input_chars) | 54,000 |
| top_p | 0.8 |
| top_k | 20 |
| presence_penalty | 1.0 |
| Length re-samples | 1 |
| Chunk window (chars) | 47000 |
| Chunk overlap (chars) | 6500 |
| Job retries | 2 |
| Dataset | Lucius-Morningstar/mailroom-dataset ground_truth @ ed7576b6, split=all, seed 42 |
| Draw | 50 docs (fingerprint aa4e596805e7) |
| Engine | awq_marlin · fp8 KV · CUDA graphs [1, 2, 4, 8, 16] · prefix caching on · thinking off |
| Admission | max_model_len 32768 · max_num_seqs 16 per replica · max_inputs 32 |

## Score & cost card

| Metric | Value |
| --- | ---: |
| **Run** |  |
| Run ID | `sand42-50-merger-specialist-awq-1l4-c8` |
| GPUs / replicas | 1 |
| Concurrency | 8 (8 per replica) |
| Documents | 50 |
| Spec hash | d573b8a9… |
| **Time** |  |
| Wall (busy) | 4,657.53 s |
| GPU seconds | 4,660.26 s |
| Cold boot | 0.44 s |
| **Cost** |  |
| Busy-window GPU $ | $1.035006 |
| Billed GPU $ | $1.035613 |
| Billed seconds | 4,660.26 s |
| Idle $ | $0.067356 (303.10 s) |
| Cost per document | $0.020712 |
| Cost per ok document | $0.020712 |
| Cost per 1M tokens | $0.1997 |
| **Tokens** |  |
| Prompt tokens | 4,867,606 |
| Completion tokens | 317,040 (6.1%) |
| Total tokens | 5,184,646 |
| Tokens per document | 103,693 |
| Per document: instructions + template | 6,178 (6.0%) |
| Per document: document text | 91,174 (87.9%) |
| Per document: output | 6,341 (6.1%) |
| Instruction tokens per model call | 750 over 412 calls |
| Token split basis | document chars ÷ 4.5 chars/token; instructions are the remainder |
| Completion p95 / max (ok docs) | 9,710 / 12,554 |
| **Throughput** |  |
| Tokens / second | 1,113.2 |
| Tokens / second per L4 | 1,113.2 |
| Documents / minute | 0.64 |
| **Latency (per document, ok rows)** |  |
| Mean | 696.71 s |
| p50 | 574.87 s |
| p95 | 1,324.95 s |
| Max | 1,627.90 s |
| **Engine (vLLM /metrics)** |  |
| Parallelism (Σ latency ÷ wall) | 7.48× of 8 |
| Slot occupancy | 93.5% |
| Coverage | replicas observed: 1 of 1 |
| Requests per replica (this run) | 426 |
| Mean TTFT per replica | 4.009 s |
| Prefix-cache hit per replica | 18.4% |
| Preemptions per replica (this run) | 0 |
| Length-capped finishes per replica (this run) | 9 |
| **GPU hardware (nvidia-smi)** | 699 samples · serving-replica nvidia-smi |
| GPU utilization | 98.3 % mean (p95 100.0 / peak 100.0 / min 0.0) |
| Sampling coverage | 100.0 % |
| GPU power draw | 71.7 W (min 34.4 / max 74.3) |
| GPU memory bandwidth | not captured |
| GPU SM clock | not captured |
| GPU temperature | 75.6 C (min 67.0 / max 82.0) |
| GPU memory used | 21,027 MiB (min 21,027 / max 21,027) |
| **Quality** |  |
| Overall extraction score | 0.0207 (sd 0.032) |
| Score min / max | 0.0000 / 0.1333 |
| Scoring method | `suite+maud` |
| Schema-valid rate | 1.00 |
| Parse errors | 0 |
| Errors | 0 / 50 |
| **Clause scoring (MAUD)** |  |
| Questions answered / labeled | 254 / 811 (31.3%) |
| Micro accuracy | 2.1% |
| Precision on answered | 6.7% |
| Clean subset | 15 / 343 |
| Suite field score (mean) | not captured |

## Figure

![Merger Agreements run dashboard](sand42-50-merger-specialist-awq-1l4-c8.card.png)

## Per-document results

| # | Document | OK | Score | Latency (s) | Prompt tok | Completion tok | Error |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `DOC-dc7f18df501aec90` | yes | 0.1333 | 434.3 | 83008 | 4647 | — |
| 2 | `DOC-c96b9c7e12f91576` | yes | 0.0000 | 445.2 | 92490 | 4713 | — |
| 3 | `DOC-d4b1a7a2b981fbf4` | yes | 0.0000 | 504.5 | 81817 | 5049 | — |
| 4 | `DOC-26933c93d649fa3f` | yes | 0.0000 | 520.7 | 96354 | 5229 | — |
| 5 | `DOC-0a733ab86f2390ae` | yes | 0.0000 | 525.2 | 81545 | 4845 | — |
| 6 | `DOC-45f801408be08af6` | yes | 0.0000 | 630.2 | 109920 | 6269 | — |
| 7 | `DOC-4f45bef14dcd1dbf` | yes | 0.0000 | 316.3 | 70774 | 3535 | — |
| 8 | `DOC-eb2b56fe30dc35f4` | yes | 0.0000 | 984.4 | 85298 | 5607 | — |
| 9 | `DOC-52f9a5be69429299` | yes | 0.0000 | 556.2 | 103918 | 6522 | — |
| 10 | `DOC-9420b777a4b0784c` | yes | 0.0000 | 615.0 | 98627 | 7222 | — |
| 11 | `DOC-b03c0d2bbbb9659e` | yes | 0.0556 | 549.0 | 113393 | 6341 | — |
| 12 | `DOC-5f5d40f6b2c338ac` | yes | 0.0000 | 1,136.1 | 109887 | 6310 | — |
| 13 | `DOC-882fabf7aba36941` | yes | 0.0000 | 365.3 | 92325 | 4183 | — |
| 14 | `DOC-e8538f75b0f993e6` | yes | 0.0000 | 753.3 | 113280 | 8172 | — |
| 15 | `DOC-511062d64bc9afc6` | yes | 0.0000 | 532.4 | 97584 | 5597 | — |
| 16 | `DOC-30eda1e78a5f6fb5` | yes | 0.0556 | 615.4 | 107499 | 6532 | — |
| 17 | `DOC-1e016055aa435e71` | yes | 0.0000 | 428.5 | 109137 | 4207 | — |
| 18 | `DOC-f90cc5fb2ceac154` | yes | 0.0000 | 493.3 | 93747 | 5674 | — |
| 19 | `DOC-5f8ef95caa2fd349` | yes | 0.0000 | 603.8 | 104105 | 6560 | — |
| 20 | `DOC-71bc59dd305ee8ed` | yes | 0.0769 | 1,212.5 | 109675 | 8024 | — |
| 21 | `DOC-63beb09b179ea4ee` | yes | 0.0588 | 577.1 | 83572 | 5566 | — |
| 22 | `DOC-37bc3c44ae2c4ef6` | yes | 0.0000 | 496.6 | 90012 | 5281 | — |
| 23 | `DOC-0534799ed39ca0db` | yes | 0.0556 | 540.8 | 92828 | 5967 | — |
| 24 | `DOC-bec74557186e9409` | yes | 0.0000 | 804.5 | 78918 | 9710 | — |
| 25 | `DOC-ab5578f1f9f04244` | yes | 0.0000 | 1,227.2 | 132059 | 9515 | — |
| 26 | `DOC-297745a521cd1e8c` | yes | 0.0000 | 709.8 | 103150 | 7546 | — |
| 27 | `DOC-2b9f668ab6cb8901` | yes | 0.0526 | 803.3 | 90831 | 4250 | — |
| 28 | `DOC-386ac6d669b7731c` | yes | 0.0769 | 415.3 | 93831 | 5142 | — |
| 29 | `DOC-fe9a8b51344d67d9` | yes | 0.0000 | 987.0 | 130099 | 12554 | — |
| 30 | `DOC-7e2818ceb0167d5a` | yes | 0.0556 | 512.3 | 78432 | 6153 | — |
| 31 | `DOC-26fa94f698c37fc5` | yes | 0.0588 | 352.9 | 79931 | 4228 | — |
| 32 | `DOC-72b0b8c8385edd48` | yes | 0.0000 | 788.2 | 84431 | 8606 | — |
| 33 | `DOC-fcaddb5bdc94ce63` | yes | 0.0000 | 520.1 | 82656 | 5381 | — |
| 34 | `DOC-ac48214468deb8dd` | yes | 0.0588 | 394.4 | 72887 | 4632 | — |
| 35 | `DOC-c6b5f7ea5f718c28` | yes | 0.0588 | 1,079.7 | 82765 | 7967 | — |
| 36 | `DOC-f9870e3b8fd141b0` | yes | 0.0000 | 720.7 | 134889 | 7810 | — |
| 37 | `DOC-b3d0149fd994357a` | yes | 0.0000 | 343.7 | 78500 | 5261 | — |
| 38 | `DOC-5d30efc302f3c431` | yes | 0.0625 | 288.7 | 130943 | 9312 | — |
| 39 | `DOC-9d34581755c603a3` | yes | 0.0000 | 902.5 | 94942 | 3760 | — |
| 40 | `DOC-03712a2b0a99a314` | yes | 0.0588 | 1,627.9 | 119367 | 7250 | — |
| 41 | `DOC-0070a4e34dddbfd5` | yes | 0.0000 | 1,482.7 | 85209 | 5797 | — |
| 42 | `DOC-1cd38a83b224335d` | yes | 0.0000 | 906.0 | 78294 | 3181 | — |
| 43 | `DOC-e6c8852b877c4598` | yes | 0.0000 | 1,307.5 | 104093 | 5925 | — |
| 44 | `DOC-f449b47c7269f288` | yes | 0.0625 | 407.3 | 95394 | 5332 | — |
| 45 | `DOC-ab735131c00271bc` | yes | 0.0556 | 1,027.4 | 81228 | 4908 | — |
| 46 | `DOC-169bbcdc5d9e609c` | yes | 0.0000 | 1,324.9 | 134911 | 9408 | — |
| 47 | `DOC-ff3ceb691481f1bd` | yes | 0.0000 | 487.1 | 91432 | 7018 | — |
| 48 | `DOC-23f224263f6974c5` | yes | 0.0000 | 326.9 | 83736 | 5723 | — |
| 49 | `DOC-f09307ad314d386f` | yes | 0.0000 | 678.5 | 103329 | 11556 | — |
| 50 | `DOC-681bc6115b882191` | yes | 0.0000 | 572.6 | 120554 | 7063 | — |

_Generated 2026-10-12T06:10:32+00:00 by `sandbox run card`. Machine-readable twin: `sand42-50-merger-specialist-awq-1l4-c8.card.json`._
