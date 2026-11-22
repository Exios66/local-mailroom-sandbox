# Run report — `sand214-30-contracts-specialist-awq-1l4-windows-r2`

Dated cell stem: `RUN-30-CONTRACTS-AWQ-1L4-C16-R2`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `sand214-30-contracts-specialist-awq-1l4-windows-r2` |
| task / agent | `contracts_specialist` |
| prompt | `contracts_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **1×L4** |
| concurrency | **16** |
| n | **30** |
| profile | `modal-vllm` |
| spec_hash | `c75f8e4e27939a8847b1ffcb21577afbbda69b5a317ca77551def0424618624d` |
| dataset fingerprint | `65919cc4ad5b` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **30 / 0 / 30** |
| **overall_extraction_score** | **0.652267** |
| schema_valid_rate | 1.000000 |
| error_count | 0 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 2793.557 |
| gpu_seconds | 2793.557 |
| estimated GPU cost | 0.620790 |
| **GPU $/doc** | **0.020693** |
| latency p50 / max (s) | 403.250079 / 1030.707178 |
| prompt / completion tokens | 993846 / 126849 |
| concurrency speedup (Σlat/wall) | 4.94 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-25f822c661011bfe` | True | 0.588200 | 257.2 | 21672 | 1975 | None |
| 2 | `DOC-62b300182901e850` | True | 0.571400 | 299.0 | 31264 | 2370 | None |
| 3 | `DOC-e53347b00c241321` | True | 0.625000 | 317.4 | 21113 | 2597 | None |
| 4 | `DOC-da32dbf12bb01d1e` | True | 0.714300 | 358.0 | 38419 | 2884 | None |
| 5 | `DOC-179c15d2e6fdf398` | True | 0.720000 | 358.7 | 18567 | 2937 | None |
| 6 | `DOC-7a46f2451bb004f0` | True | 0.628600 | 381.3 | 14916 | 3023 | None |
| 7 | `DOC-e9d0a5cfff56fa37` | True | 0.260900 | 457.2 | 36897 | 3887 | None |
| 8 | `DOC-c43f58d93eac3a4d` | True | 0.480000 | 504.5 | 15282 | 4266 | None |
| 9 | `DOC-e29140d2e8e989be` | True | 0.777800 | 561.9 | 42709 | 4847 | None |
| 10 | `DOC-1e0e6ca042300b31` | True | 0.742900 | 587.4 | 46367 | 5061 | None |
| 11 | `DOC-2b510409d3b9a4a6` | True | 0.730800 | 601.9 | 20280 | 5181 | None |
| 12 | `DOC-8cae10ecec1f5866` | True | 0.800000 | 645.9 | 44025 | 5564 | None |
| 13 | `DOC-78e5dbaae50afc77` | True | 0.714300 | 310.1 | 18179 | 2869 | None |
| 14 | `DOC-5a81b8611e5a352c` | True | 0.500000 | 698.5 | 45411 | 6049 | None |
| 15 | `DOC-52daf47a1de2bcc1` | True | 0.750000 | 428.8 | 27960 | 3953 | None |
| 16 | `DOC-2c8bbcb1a7ca7668` | True | 0.350000 | 425.2 | 20894 | 3946 | None |
| 17 | `DOC-6c55617151b6c336` | True | 0.720000 | 344.8 | 30504 | 3284 | None |
| 18 | `DOC-e69313c4bb90489c` | True | 0.481500 | 816.8 | 71206 | 7356 | None |
| 19 | `DOC-3ce2fb9a704b18e6` | True | 0.717900 | 477.8 | 28715 | 4701 | None |
| 20 | `DOC-4ab8d1d37d3af05c` | True | 0.761900 | 338.7 | 16561 | 3492 | None |
| 21 | `DOC-dfd20f94bb76b6e4` | True | 0.583300 | 208.4 | 19612 | 2330 | None |
| 22 | `DOC-8a776dec500b074c` | True | 0.588200 | 483.8 | 44422 | 5063 | None |
| 23 | `DOC-13000a5067f49a46` | True | 0.754700 | 305.7 | 32202 | 3340 | None |
| 24 | `DOC-054679d45a654d0a` | True | 0.720000 | 269.9 | 15163 | 3090 | None |
| 25 | `DOC-d96559c6d045fcb2` | True | 0.750000 | 632.4 | 64670 | 6625 | None |
| 26 | `DOC-67a58cedb39a4e4f` | True | 0.733300 | 236.3 | 15950 | 3304 | None |
| 27 | `DOC-f76f6e3e45039acb` | True | 0.689700 | 324.4 | 31089 | 4247 | None |
| 28 | `DOC-a83cc1f1ab0c757e` | True | 0.631600 | 217.1 | 21283 | 3369 | None |
| 29 | `DOC-29c516a4775b07d9` | True | 0.750000 | 932.2 | 88682 | 9955 | None |
| 30 | `DOC-30c38dd3a2964c8e` | True | 0.731700 | 1030.7 | 49832 | 5284 | None |
