# Corporate Records — 1× L4 · C8 · n=50

**Run:** `sand42-50-corporate-records-specialist-awq-1l4-c8` · **Model:** Qwen/Qwen3-8B-AWQ · vLLM v0.29.0 · Modal `sandbox-vllm` · L4 @ $0.80/GPU-hr

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
| Run ID | `sand42-50-corporate-records-specialist-awq-1l4-c8` |
| GPUs / replicas | 1 |
| Concurrency | 8 (8 per replica) |
| Documents | 50 |
| Spec hash | 4640639b… |
| **Time** |  |
| Wall (busy) | 86.60 s |
| GPU seconds | 87.28 s |
| Cold boot | 0.48 s |
| **Cost** |  |
| Busy-window GPU $ | $0.019244 |
| Billed GPU $ | $0.019396 |
| Billed seconds | 87.28 s |
| Idle $ | $0.003769 (16.96 s) |
| Cost per document | $0.000388 |
| Cost per ok document | $0.000388 |
| Cost per 1M tokens | $0.0944 |
| **Tokens** |  |
| Prompt tokens | 197,319 |
| Completion tokens | 8,051 (3.9%) |
| Total tokens | 205,370 |
| Tokens per document | 4,107 |
| Per document: instructions + template | 2,090 (50.9%) |
| Per document: document text | 1,856 (45.2%) |
| Per document: output | 161 (3.9%) |
| Instruction tokens per model call | 2,090 over 50 calls |
| Token split basis | fit across documents, 4.21 chars/token |
| Completion p95 / max (ok docs) | 198 / 242 |
| **Throughput** |  |
| Tokens / second | 2,371.5 |
| Tokens / second per L4 | 2,371.5 |
| Documents / minute | 34.64 |
| **Latency (per document, ok rows)** |  |
| Mean | 11.14 s |
| p50 | 11.23 s |
| p95 | 13.64 s |
| Max | 16.50 s |
| **Engine (vLLM /metrics)** |  |
| Parallelism (Σ latency ÷ wall) | 6.43× of 8 |
| Slot occupancy | 80.4% |
| Coverage | replicas observed: 1 of 1 |
| Requests per replica (this run) | 50 |
| Mean TTFT per replica | 1.209 s |
| Prefix-cache hit per replica | 50.9% |
| Preemptions per replica (this run) | 0 |
| Length-capped finishes per replica (this run) | 0 |
| **GPU hardware (nvidia-smi)** | 14 samples · serving-replica nvidia-smi |
| GPU utilization | 77.6 % mean (p95 100.0 / peak 100.0 / min 0.0) |
| Sampling coverage | 100.0 % |
| GPU power draw | 63.4 W (min 31.7 / max 72.4) |
| GPU memory bandwidth | not captured |
| GPU SM clock | not captured |
| GPU temperature | 64.4 C (min 57.0 / max 69.0) |
| GPU memory used | 21,023 MiB (min 21,023 / max 21,023) |
| **Quality** |  |
| Overall extraction score | 0.4968 (sd 0.254) |
| Score min / max | 0.0635 / 0.8889 |
| Scoring method | `suite` |
| Schema-valid rate | 0.96 |
| Parse errors | 0 |
| Errors | 0 / 50 |

## Figure

![Corporate Records run dashboard](sand42-50-corporate-records-specialist-awq-1l4-c8.card.png)

## Per-document results

| # | Document | OK | Score | Latency (s) | Prompt tok | Completion tok | Error |
| ---: | --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | `DOC-020d77c0107d273d` | yes | 0.4746 | 10.1 | 2302 | 107 | — |
| 2 | `DOC-9ca44c7926a47ede` | yes | 0.5024 | 10.2 | 2292 | 131 | — |
| 3 | `DOC-6790430ae2a6c724` | yes | 0.1846 | 10.6 | 4477 | 144 | — |
| 4 | `DOC-fbcdd16e24f143ac` | yes | 0.1582 | 13.4 | 2456 | 155 | — |
| 5 | `DOC-e545bbd5f5ea61b6` | yes | 0.3636 | 13.4 | 2788 | 160 | — |
| 6 | `DOC-81ae205a3b0bf16f` | yes | 0.2480 | 13.4 | 2515 | 158 | — |
| 7 | `DOC-01054efd0980066b` | yes | 0.8222 | 13.6 | 5122 | 167 | — |
| 8 | `DOC-12a6d4cd092cf66d` | yes | 0.5026 | 13.6 | 7710 | 158 | — |
| 9 | `DOC-91f89b9c0d285ac7` | yes | 0.6667 | 11.9 | 6902 | 128 | — |
| 10 | `DOC-c4c9c37a96291975` | yes | 0.0813 | 12.1 | 2424 | 136 | — |
| 11 | `DOC-0a262afc80c73247` | yes | 0.1136 | 13.3 | 3124 | 156 | — |
| 12 | `DOC-a040ac19abb88fec` | yes | 0.4097 | 11.0 | 2206 | 141 | — |
| 13 | `DOC-0f56fe8db6df01bd` | yes | 0.0635 | 13.0 | 5368 | 163 | — |
| 14 | `DOC-732b812b7d9d9653` | yes | 0.8889 | 13.0 | 5572 | 165 | — |
| 15 | `DOC-2819b889b134ea01` | yes | 0.7500 | 13.3 | 5344 | 171 | — |
| 16 | `DOC-68d5a8753fcc3675` | yes | 0.4405 | 13.1 | 5671 | 175 | — |
| 17 | `DOC-9376c6bfa6779d5e` | yes | 0.4822 | 7.1 | 2200 | 131 | — |
| 18 | `DOC-e077f1f7e80e1e04` | yes | 0.1624 | 9.1 | 4043 | 165 | — |
| 19 | `DOC-b3ad98e5530dfeaf` | yes | 0.2820 | 10.5 | 2521 | 190 | — |
| 20 | `DOC-2f19002c84083aa8` | yes | 0.4978 | 8.5 | 5200 | 165 | — |
| 21 | `DOC-f134b9491efc5c57` | yes | 0.7949 | 6.7 | 2865 | 140 | — |
| 22 | `DOC-4dc719baa790a79c` | yes | 0.6667 | 10.6 | 2669 | 163 | — |
| 23 | `DOC-fc9f56d999bd7566` | yes | 0.6667 | 12.7 | 2509 | 196 | — |
| 24 | `DOC-1e8e3ce47882ae71` | yes | 0.1485 | 12.8 | 3063 | 198 | — |
| 25 | `DOC-474a0002b4c03be1` | yes | 0.8205 | 10.9 | 2938 | 155 | — |
| 26 | `DOC-e478fa89043a29e3` | yes | 0.8205 | 11.5 | 2910 | 151 | — |
| 27 | `DOC-a5fd7fe18b094f20` | yes | 0.8485 | 9.8 | 5919 | 145 | — |
| 28 | `DOC-d015968793450753` | yes | 0.7222 | 12.1 | 5082 | 159 | — |
| 29 | `DOC-9467462d9bb34f8e` | yes | 0.5417 | 9.8 | 5345 | 156 | — |
| 30 | `DOC-204c3c7c0ba021cd` | yes | 0.4746 | 9.7 | 2226 | 152 | — |
| 31 | `DOC-b832b5eaa2b4848c` | yes | 0.1068 | 9.8 | 2762 | 157 | — |
| 32 | `DOC-41b53ea487b84955` | yes | 0.7500 | 16.5 | 4617 | 242 | — |
| 33 | `DOC-37152a33cfb70d37` | yes | 0.7436 | 10.5 | 2902 | 139 | — |
| 34 | `DOC-bfa92eb6c72569ee` | yes | 0.1184 | 11.4 | 3771 | 158 | — |
| 35 | `DOC-00193d0c070747e6` | yes | 0.7143 | 12.4 | 3225 | 181 | — |
| 36 | `DOC-0a8eb16fff7e67ca` | yes | 0.6923 | 9.4 | 5246 | 150 | — |
| 37 | `DOC-ffb48271e0a5e812` | yes | 0.6667 | 9.3 | 5344 | 142 | — |
| 38 | `DOC-a973ebf005e0e785` | yes | 0.4278 | 15.8 | 6146 | 234 | — |
| 39 | `DOC-f21f3dadebb121e3` | yes | 0.7843 | 11.4 | 3308 | 180 | — |
| 40 | `DOC-80e90a37bb750a3c` | yes | 0.1495 | 11.1 | 2776 | 183 | — |
| 41 | `DOC-78f2456f571403a9` | yes | 0.1531 | 12.2 | 2345 | 144 | — |
| 42 | `DOC-e6906e59f9bd74ca` | yes | 0.6200 | 12.3 | 2978 | 160 | — |
| 43 | `DOC-d4dfbfe8049d41f9` | yes | 0.4934 | 13.0 | 3856 | 175 | — |
| 44 | `DOC-2338d194d5250def` | yes | 0.4867 | 9.8 | 5258 | 128 | — |
| 45 | `DOC-866139125545b36a` | yes | 0.7733 | 12.5 | 5397 | 180 | — |
| 46 | `DOC-606242f2919653a4` | yes | 0.2332 | 9.5 | 5253 | 160 | — |
| 47 | `DOC-dfe42f3747f299e6` | yes | 0.7500 | 9.3 | 5870 | 158 | — |
| 48 | `DOC-842215e36884da89` | yes | 0.2467 | 9.5 | 5226 | 164 | — |
| 49 | `DOC-d0aebe650be3e512` | yes | 0.4976 | 5.5 | 2405 | 161 | — |
| 50 | `DOC-27bbad54b6fd107e` | yes | 0.8333 | 5.5 | 2871 | 174 | — |

_Generated 2026-10-12T06:10:29+00:00 by `sandbox run card`. Machine-readable twin: `sand42-50-corporate-records-specialist-awq-1l4-c8.card.json`._
