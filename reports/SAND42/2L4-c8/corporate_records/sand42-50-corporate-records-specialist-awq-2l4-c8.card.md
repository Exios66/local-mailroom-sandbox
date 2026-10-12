# Corporate Records — 2× L4 · C8 · n=50

**Run:** `sand42-50-corporate-records-specialist-awq-2l4-c8` · **Model:** Qwen/Qwen3-8B-AWQ · vLLM v0.29.0 · Modal `sandbox-vllm` · L4 @ $0.80/GPU-hr

## Conditions

| Condition | Value |
| --- | --- |
| Task | corporate_records_specialist |
| Prompt | corporate_records_specialist_simplified |
| Temperature | 0.1 (vendored call site) |
| Output cap (max_tokens) | 8,192 |
| Input cap (max_input_chars) | 15,000 |
| Job retries | 2 |
| Dataset | Lucius-Morningstar/mailroom-dataset ground_truth @ ed7576b6, split=all, seed 42 |
| Draw | 50 docs (fingerprint 76b083c7c46d) |
| Engine | awq_marlin · fp8 KV · CUDA graphs [1, 2, 4, 8, 16] · prefix caching on · thinking off |
| Admission | max_model_len 32768 · max_num_seqs 16 per replica · max_inputs 32 |

## Score & cost card

| Metric | Value |
| --- | ---: |
| **Run** |  |
| Run ID | `sand42-50-corporate-records-specialist-awq-2l4-c8` |
| GPUs / replicas | 2 |
| Concurrency | 8 (4 per replica) |
| Documents | 50 |
| Spec hash | b13d7fb4… |
| **Time** |  |
| Wall (busy) | 64.93 s |
| GPU seconds | 66.17 s |
| Cold boot | 0.30 s |
| **Cost** |  |
| Busy-window GPU $ | $0.028856 |
| Billed GPU $ | $0.029409 |
| Billed seconds | 66.17 s |
| Idle $ | $0.007346 (16.53 s) |
| Cost per document | $0.000588 |
| Cost per ok document | $0.000588 |
| Cost per 1M tokens | $0.1432 |
| **Tokens** |  |
| Prompt tokens | 197,319 |
| Completion tokens | 8,006 (3.9%) |
| Total tokens | 205,325 |
| Tokens per document | 4,106 |
| Per document: instructions + template | 2,090 (50.9%) |
| Per document: document text | 1,856 (45.2%) |
| Per document: output | 160 (3.9%) |
| Instruction tokens per model call | 2,090 over 50 calls |
| Token split basis | fit across documents, 4.21 chars/token |
| Completion p95 / max (ok docs) | 201 / 233 |
| **Throughput** |  |
| Tokens / second | 3,162.4 |
| Tokens / second per L4 | 1,581.2 |
| Documents / minute | 46.21 |
| **Latency (per document, ok rows)** |  |
| Mean | 7.74 s |
| p50 | 7.73 s |
| p95 | 11.45 s |
| Max | 12.27 s |
| **Engine (vLLM /metrics)** |  |
| Parallelism (Σ latency ÷ wall) | 5.96× of 8 |
| Slot occupancy | 74.5% |
| Coverage | replicas observed: 2 of 2 |
| Requests per replica (this run) | 26 / 24 |
| Mean TTFT per replica | 0.802 s / 0.915 s |
| Prefix-cache hit per replica | 52.8% / 47.0% |
| Preemptions per replica (this run) | 0 / 0 |
| Length-capped finishes per replica (this run) | 0 / 0 |
| **GPU hardware (nvidia-smi)** | 21 samples · serving-replica nvidia-smi |
| GPU utilization | 79.6 % mean (p95 100.0 / peak 100.0 / min 0.0) |
| Sampling coverage | 100.0 % |
| GPU power draw | 62.8 W (min 32.5 / max 72.4) of 72 W cap |
| GPU memory bandwidth | 64.5 % (min 0.0 / max 100.0) |
| GPU SM clock | 1,441 MHz (min 945 / max 2,040) |
| GPU temperature | 77.0 C (min 70.0 / max 81.0) |
| GPU memory used | 20,997 MiB (min 20,996 / max 20,998) |
| **Quality** |  |
| Overall extraction score | 0.4806 (sd 0.249) |
| Score min / max | 0.0635 / 0.8889 |
| Scoring method | `suite` |
| Schema-valid rate | 0.96 |
| Parse errors | 0 |
| Errors | 0 / 50 |

## Figure

![Corporate Records run dashboard](sand42-50-corporate-records-specialist-awq-2l4-c8.card.png)

## Per-document results

| # | Document | OK | Score | Latency (s) | Prompt tok | Completion tok | Error |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `DOC-9ca44c7926a47ede` | yes | 0.5024 | 5.8 | 2292 | 130 | — |
| 2 | `DOC-020d77c0107d273d` | yes | 0.4746 | 5.8 | 2302 | 116 | — |
| 3 | `DOC-fbcdd16e24f143ac` | yes | 0.1582 | 8.2 | 2456 | 155 | — |
| 4 | `DOC-e545bbd5f5ea61b6` | yes | 0.3636 | 8.2 | 2788 | 156 | — |
| 5 | `DOC-81ae205a3b0bf16f` | yes | 0.2480 | 8.3 | 2515 | 163 | — |
| 6 | `DOC-6790430ae2a6c724` | yes | 0.1846 | 11.0 | 4477 | 142 | — |
| 7 | `DOC-12a6d4cd092cf66d` | yes | 0.5026 | 11.5 | 7710 | 158 | — |
| 8 | `DOC-01054efd0980066b` | yes | 0.8222 | 11.5 | 5122 | 159 | — |
| 9 | `DOC-c4c9c37a96291975` | yes | 0.0813 | 5.6 | 2424 | 136 | — |
| 10 | `DOC-91f89b9c0d285ac7` | yes | 0.6667 | 6.8 | 6902 | 128 | — |
| 11 | `DOC-a040ac19abb88fec` | yes | 0.4097 | 7.3 | 2206 | 141 | — |
| 12 | `DOC-0a262afc80c73247` | yes | 0.1136 | 7.7 | 3124 | 153 | — |
| 13 | `DOC-0f56fe8db6df01bd` | yes | 0.0635 | 9.9 | 5368 | 161 | — |
| 14 | `DOC-732b812b7d9d9653` | yes | 0.8889 | 7.7 | 5572 | 156 | — |
| 15 | `DOC-68d5a8753fcc3675` | yes | 0.4405 | 8.3 | 5671 | 177 | — |
| 16 | `DOC-e077f1f7e80e1e04` | yes | 0.1624 | 8.7 | 4043 | 160 | — |
| 17 | `DOC-9376c6bfa6779d5e` | yes | 0.4519 | 4.6 | 2200 | 134 | — |
| 18 | `DOC-2819b889b134ea01` | yes | 0.7500 | 9.5 | 5344 | 175 | — |
| 19 | `DOC-b3ad98e5530dfeaf` | yes | 0.2820 | 9.0 | 2521 | 190 | — |
| 20 | `DOC-2f19002c84083aa8` | yes | 0.4951 | 7.3 | 5200 | 170 | — |
| 21 | `DOC-f134b9491efc5c57` | yes | 0.7949 | 6.0 | 2865 | 140 | — |
| 22 | `DOC-474a0002b4c03be1` | yes | 0.8205 | 6.1 | 2938 | 152 | — |
| 23 | `DOC-4dc719baa790a79c` | yes | 0.6667 | 6.7 | 2669 | 163 | — |
| 24 | `DOC-e478fa89043a29e3` | yes | 0.8205 | 6.7 | 2910 | 151 | — |
| 25 | `DOC-fc9f56d999bd7566` | yes | 0.6667 | 8.4 | 2509 | 196 | — |
| 26 | `DOC-1e8e3ce47882ae71` | yes | 0.1485 | 9.5 | 3063 | 198 | — |
| 27 | `DOC-d015968793450753` | yes | 0.8056 | 7.9 | 5082 | 167 | — |
| 28 | `DOC-a5fd7fe18b094f20` | yes | 0.8485 | 7.6 | 5919 | 145 | — |
| 29 | `DOC-b832b5eaa2b4848c` | yes | 0.1068 | 4.2 | 2762 | 95 | — |
| 30 | `DOC-204c3c7c0ba021cd` | yes | 0.4746 | 7.1 | 2226 | 133 | — |
| 31 | `DOC-41b53ea487b84955` | yes | 0.7500 | 10.0 | 4617 | 233 | — |
| 32 | `DOC-bfa92eb6c72569ee` | yes | 0.1184 | 7.3 | 3771 | 158 | — |
| 33 | `DOC-9467462d9bb34f8e` | yes | 0.5417 | 9.3 | 5345 | 160 | — |
| 34 | `DOC-37152a33cfb70d37` | yes | 0.4103 | 6.6 | 2902 | 161 | — |
| 35 | `DOC-0a8eb16fff7e67ca` | yes | 0.3590 | 6.5 | 5246 | 159 | — |
| 36 | `DOC-00193d0c070747e6` | yes | 0.7143 | 9.0 | 3225 | 173 | — |
| 37 | `DOC-f21f3dadebb121e3` | yes | 0.7843 | 6.3 | 3308 | 180 | — |
| 38 | `DOC-78f2456f571403a9` | yes | 0.1531 | 5.0 | 2345 | 151 | — |
| 39 | `DOC-ffb48271e0a5e812` | yes | 0.6667 | 8.8 | 5344 | 141 | — |
| 40 | `DOC-a973ebf005e0e785` | yes | 0.4278 | 12.3 | 6146 | 211 | — |
| 41 | `DOC-e6906e59f9bd74ca` | yes | 0.6200 | 9.1 | 2978 | 160 | — |
| 42 | `DOC-d4dfbfe8049d41f9` | yes | 0.4907 | 7.9 | 3856 | 179 | — |
| 43 | `DOC-80e90a37bb750a3c` | yes | 0.1654 | 10.4 | 2776 | 201 | — |
| 44 | `DOC-2338d194d5250def` | yes | 0.4867 | 6.4 | 5258 | 128 | — |
| 45 | `DOC-866139125545b36a` | yes | 0.7733 | 9.5 | 5397 | 180 | — |
| 46 | `DOC-842215e36884da89` | yes | 0.2467 | 5.7 | 5226 | 158 | — |
| 47 | `DOC-606242f2919653a4` | yes | 0.2332 | 7.8 | 5253 | 165 | — |
| 48 | `DOC-dfe42f3747f299e6` | yes | 0.7500 | 6.5 | 5870 | 166 | — |
| 49 | `DOC-d0aebe650be3e512` | yes | 0.4976 | 4.5 | 2405 | 163 | — |
| 50 | `DOC-27bbad54b6fd107e` | yes | 0.6250 | 5.2 | 2871 | 179 | — |

_Generated 2026-10-12T06:32:57+00:00 by `sandbox run card`. Machine-readable twin: `sand42-50-corporate-records-specialist-awq-2l4-c8.card.json`._
