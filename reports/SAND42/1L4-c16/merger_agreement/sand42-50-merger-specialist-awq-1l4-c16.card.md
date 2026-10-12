# Merger Agreements — 1× L4 · C16 · n=50

**Run:** `sand42-50-merger-specialist-awq-1l4-c16` · **Model:** Qwen/Qwen3-8B-AWQ · vLLM v0.29.0 · Modal `sandbox-vllm` · L4 @ $0.80/GPU-hr

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
| Run ID | `sand42-50-merger-specialist-awq-1l4-c16` |
| GPUs / replicas | 1 |
| Concurrency | 16 (16 per replica) |
| Documents | 50 |
| Spec hash | 29ddbe9d… |
| **Time** |  |
| Wall (busy) | 4,098.52 s |
| GPU seconds | 4,099.38 s |
| Cold boot | 0.37 s |
| **Cost** |  |
| Busy-window GPU $ | $0.910783 |
| Billed GPU $ | $0.910974 |
| Billed seconds | 4,099.38 s |
| Idle $ | $0.104106 (468.48 s) |
| Cost per document | $0.018219 |
| Cost per ok document | $0.018219 |
| Cost per 1M tokens | $0.1761 |
| **Tokens** |  |
| Prompt tokens | 4,867,606 |
| Completion tokens | 304,542 (5.9%) |
| Total tokens | 5,172,148 |
| Tokens per document | 103,443 |
| Per document: instructions + template | 6,178 (6.0%) |
| Per document: document text | 91,174 (88.1%) |
| Per document: output | 6,091 (5.9%) |
| Instruction tokens per model call | 750 over 412 calls |
| Token split basis | document chars ÷ 4.5 chars/token; instructions are the remainder |
| Completion p95 / max (ok docs) | 8,642 / 14,580 |
| **Throughput** |  |
| Tokens / second | 1,262.0 |
| Tokens / second per L4 | 1,262.0 |
| Documents / minute | 0.73 |
| **Latency (per document, ok rows)** |  |
| Mean | 1,161.62 s |
| p50 | 1,045.56 s |
| p95 | 1,891.20 s |
| Max | 2,405.98 s |
| **Engine (vLLM /metrics)** |  |
| Parallelism (Σ latency ÷ wall) | 14.17× of 16 |
| Slot occupancy | 88.6% |
| Coverage | replicas observed: 1 of 1 |
| Requests per replica (this run) | 430 |
| Mean TTFT per replica | 6.711 s |
| Prefix-cache hit per replica | 14.0% |
| Preemptions per replica (this run) | 0 |
| Length-capped finishes per replica (this run) | 10 |
| **GPU hardware (nvidia-smi)** | 651 samples · serving-replica nvidia-smi |
| GPU utilization | 98.2 % mean (p95 100.0 / peak 100.0 / min 0.0) |
| Sampling coverage | 100.0 % |
| GPU power draw | 71.7 W (min 34.5 / max 76.0) of 72 W cap |
| GPU memory bandwidth | 78.2 % (min 0.0 / max 100.0) |
| GPU SM clock | 1,244 MHz (min 975 / max 2,040) |
| GPU temperature | 76.5 C (min 71.0 / max 81.0) |
| GPU memory used | 21,027 MiB (min 21,024 / max 21,028) |
| **Quality** |  |
| Overall extraction score | 0.0290 (sd 0.036) |
| Score min / max | 0.0000 / 0.1333 |
| Scoring method | `suite+maud` |
| Schema-valid rate | 1.00 |
| Parse errors | 0 |
| Errors | 0 / 50 |
| **Clause scoring (MAUD)** |  |
| Questions answered / labeled | 247 / 811 (30.5%) |
| Micro accuracy | 2.8% |
| Precision on answered | 9.3% |
| Clean subset | 17 / 343 |
| Suite field score (mean) | not captured |

## Figure

![Merger Agreements run dashboard](sand42-50-merger-specialist-awq-1l4-c16.card.png)

## Per-document results

| # | Document | OK | Score | Latency (s) | Prompt tok | Completion tok | Error |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `DOC-30eda1e78a5f6fb5` | yes | 0.0000 | 982.4 | 107499 | 11510 | — |
| 2 | `DOC-d4b1a7a2b981fbf4` | yes | 0.1176 | 1,192.4 | 81817 | 4038 | — |
| 3 | `DOC-882fabf7aba36941` | yes | 0.0000 | 1,369.9 | 92325 | 4188 | — |
| 4 | `DOC-dc7f18df501aec90` | yes | 0.0667 | 1,421.8 | 83008 | 4440 | — |
| 5 | `DOC-4f45bef14dcd1dbf` | yes | 0.0625 | 1,444.6 | 70774 | 3807 | — |
| 6 | `DOC-0a733ab86f2390ae` | yes | 0.0667 | 1,482.2 | 81545 | 5091 | — |
| 7 | `DOC-26933c93d649fa3f` | yes | 0.0000 | 1,494.7 | 96354 | 5000 | — |
| 8 | `DOC-eb2b56fe30dc35f4` | yes | 0.0588 | 1,533.4 | 85298 | 5396 | — |
| 9 | `DOC-9420b777a4b0784c` | yes | 0.0000 | 1,553.1 | 98627 | 5433 | — |
| 10 | `DOC-c96b9c7e12f91576` | yes | 0.0000 | 1,568.3 | 92490 | 5517 | — |
| 11 | `DOC-52f9a5be69429299` | yes | 0.0000 | 1,650.9 | 103918 | 6158 | — |
| 12 | `DOC-45f801408be08af6` | yes | 0.1333 | 1,739.9 | 109920 | 6615 | — |
| 13 | `DOC-e8538f75b0f993e6` | yes | 0.0000 | 1,799.5 | 113280 | 7115 | — |
| 14 | `DOC-71bc59dd305ee8ed` | yes | 0.0769 | 1,891.2 | 109675 | 7660 | — |
| 15 | `DOC-511062d64bc9afc6` | yes | 0.0000 | 1,180.8 | 97584 | 7550 | — |
| 16 | `DOC-5f5d40f6b2c338ac` | yes | 0.0000 | 2,164.4 | 109887 | 7774 | — |
| 17 | `DOC-ab5578f1f9f04244` | yes | 0.0667 | 1,055.1 | 132059 | 6681 | — |
| 18 | `DOC-f90cc5fb2ceac154` | yes | 0.0000 | 843.1 | 93747 | 5491 | — |
| 19 | `DOC-63beb09b179ea4ee` | yes | 0.0588 | 781.9 | 83572 | 5057 | — |
| 20 | `DOC-bec74557186e9409` | yes | 0.0000 | 827.2 | 78918 | 5307 | — |
| 21 | `DOC-1e016055aa435e71` | yes | 0.0000 | 927.7 | 109137 | 5923 | — |
| 22 | `DOC-b03c0d2bbbb9659e` | yes | 0.0000 | 2,406.0 | 113393 | 4854 | — |
| 23 | `DOC-5f8ef95caa2fd349` | yes | 0.0000 | 1,043.0 | 104105 | 6600 | — |
| 24 | `DOC-2b9f668ab6cb8901` | yes | 0.0526 | 847.0 | 90831 | 5285 | — |
| 25 | `DOC-c6b5f7ea5f718c28` | yes | 0.0588 | 767.4 | 82765 | 4799 | — |
| 26 | `DOC-0534799ed39ca0db` | yes | 0.0000 | 1,031.0 | 92828 | 6470 | — |
| 27 | `DOC-37bc3c44ae2c4ef6` | yes | 0.0000 | 1,048.1 | 90012 | 6529 | — |
| 28 | `DOC-fe9a8b51344d67d9` | yes | 0.0833 | 1,212.3 | 130099 | 7517 | — |
| 29 | `DOC-386ac6d669b7731c` | yes | 0.0769 | 1,004.6 | 93831 | 6068 | — |
| 30 | `DOC-fcaddb5bdc94ce63` | yes | 0.0000 | 638.5 | 82656 | 3782 | — |
| 31 | `DOC-297745a521cd1e8c` | yes | 0.0000 | 1,266.4 | 103150 | 7805 | — |
| 32 | `DOC-72b0b8c8385edd48` | yes | 0.0556 | 867.3 | 84431 | 5196 | — |
| 33 | `DOC-ac48214468deb8dd` | yes | 0.0588 | 836.5 | 72887 | 5002 | — |
| 34 | `DOC-1cd38a83b224335d` | yes | 0.0588 | 642.5 | 78294 | 3890 | — |
| 35 | `DOC-03712a2b0a99a314` | yes | 0.0000 | 1,017.1 | 119367 | 5985 | — |
| 36 | `DOC-b3d0149fd994357a` | yes | 0.0000 | 724.4 | 78500 | 4423 | — |
| 37 | `DOC-f9870e3b8fd141b0` | yes | 0.0000 | 1,066.1 | 134889 | 6523 | — |
| 38 | `DOC-9d34581755c603a3` | yes | 0.0000 | 866.1 | 94942 | 5369 | — |
| 39 | `DOC-ab735131c00271bc` | yes | 0.0556 | 745.0 | 81228 | 5032 | — |
| 40 | `DOC-f449b47c7269f288` | yes | 0.0625 | 550.2 | 95394 | 3862 | — |
| 41 | `DOC-169bbcdc5d9e609c` | yes | 0.0000 | 1,023.4 | 134911 | 7092 | — |
| 42 | `DOC-0070a4e34dddbfd5` | yes | 0.0000 | 1,241.8 | 85209 | 8642 | — |
| 43 | `DOC-ff3ceb691481f1bd` | yes | 0.0000 | 637.2 | 91432 | 5337 | — |
| 44 | `DOC-5d30efc302f3c431` | yes | 0.0625 | 850.6 | 130943 | 7341 | — |
| 45 | `DOC-681bc6115b882191` | yes | 0.0000 | 527.1 | 120554 | 5602 | — |
| 46 | `DOC-26fa94f698c37fc5` | yes | 0.0588 | 1,522.7 | 79931 | 5824 | — |
| 47 | `DOC-f09307ad314d386f` | yes | 0.0000 | 791.6 | 103329 | 7735 | — |
| 48 | `DOC-23f224263f6974c5` | yes | 0.0000 | 568.5 | 83736 | 7104 | — |
| 49 | `DOC-7e2818ceb0167d5a` | yes | 0.0556 | 1,763.6 | 78432 | 4543 | — |
| 50 | `DOC-e6c8852b877c4598` | yes | 0.0000 | 1,670.2 | 104093 | 14580 | — |

_Generated 2026-10-12T08:00:27+00:00 by `sandbox run card`. Machine-readable twin: `sand42-50-merger-specialist-awq-1l4-c16.card.json`._
