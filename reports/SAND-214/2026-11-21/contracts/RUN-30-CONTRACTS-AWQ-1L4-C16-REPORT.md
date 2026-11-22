# Run report — `sand214-30-contracts-specialist-awq-1l4-windows`

Dated cell stem: `RUN-30-CONTRACTS-AWQ-1L4-C16`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `sand214-30-contracts-specialist-awq-1l4-windows` |
| task / agent | `contracts_specialist` |
| prompt | `contracts_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **1×L4** |
| concurrency | **16** |
| n | **30** |
| profile | `modal-vllm` |
| spec_hash | `38603971f1e3a3788564f5b849f0b222a37bd98dac1100c77db90915bfaf2273` |
| dataset fingerprint | `65919cc4ad5b` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **30 / 0 / 30** |
| **overall_extraction_score** | **0.615817** |
| schema_valid_rate | 1.000000 |
| error_count | 0 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 1487.821 |
| gpu_seconds | 1487.821 |
| estimated GPU cost | 0.330627 |
| **GPU $/doc** | **0.011021** |
| latency p50 / max (s) | 444.308108 / 1478.657052 |
| prompt / completion tokens | 992551 / 140482 |
| concurrency speedup (Σlat/wall) | 11.78 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-25f822c661011bfe` | True | 0.666700 | 264.5 | 23108 | 2241 | None |
| 2 | `DOC-c43f58d93eac3a4d` | True | 0.733300 | 336.6 | 16718 | 2917 | None |
| 3 | `DOC-7a46f2451bb004f0` | True | 0.628600 | 376.9 | 16352 | 3320 | None |
| 4 | `DOC-179c15d2e6fdf398` | True | 0.689700 | 393.3 | 20003 | 3432 | None |
| 5 | `DOC-e9d0a5cfff56fa37` | True | 0.500000 | 454.7 | 39051 | 3930 | None |
| 6 | `DOC-62b300182901e850` | True | 0.666700 | 487.2 | 33418 | 4259 | None |
| 7 | `DOC-5a81b8611e5a352c` | True | 0.615400 | 502.8 | 48283 | 4321 | None |
| 8 | `DOC-30c38dd3a2964c8e` | True | 0.800000 | 610.6 | 52704 | 5489 | None |
| 9 | `DOC-1e0e6ca042300b31` | True | 0.666700 | 630.1 | 49239 | 5631 | None |
| 10 | `DOC-52daf47a1de2bcc1` | True | 0.606100 | 305.2 | 30114 | 2798 | None |
| 11 | `DOC-da32dbf12bb01d1e` | True | 0.375000 | 670.8 | 41291 | 6037 | None |
| 12 | `DOC-2b510409d3b9a4a6` | True | 0.562500 | 761.1 | 21716 | 6883 | None |
| 13 | `DOC-78e5dbaae50afc77` | True | 0.666700 | 319.0 | 19615 | 3010 | None |
| 14 | `DOC-3ce2fb9a704b18e6` | True | 0.717900 | 433.9 | 30869 | 4029 | None |
| 15 | `DOC-6c55617151b6c336` | True | 0.647100 | 404.8 | 32658 | 3852 | None |
| 16 | `DOC-13000a5067f49a46` | True | 0.693900 | 282.3 | 34356 | 2632 | None |
| 17 | `DOC-4ab8d1d37d3af05c` | True | 0.714300 | 305.8 | 17997 | 2864 | None |
| 18 | `DOC-054679d45a654d0a` | True | 0.454500 | 276.6 | 16599 | 2646 | None |
| 19 | `DOC-dfd20f94bb76b6e4` | True | 0.615400 | 247.1 | 21048 | 2679 | None |
| 20 | `DOC-8a776dec500b074c` | True | 0.693900 | 544.1 | 47294 | 5653 | None |
| 21 | `DOC-d96559c6d045fcb2` | True | 0.680900 | 780.7 | 68978 | 7796 | None |
| 22 | `DOC-f76f6e3e45039acb` | True | 0.850000 | 414.1 | 33243 | 4509 | None |
| 23 | `DOC-e53347b00c241321` | True | 0.296300 | 1058.8 | 10513 | 2176 | None |
| 24 | `DOC-a83cc1f1ab0c757e` | True | 0.571400 | 245.0 | 22719 | 3122 | None |
| 25 | `DOC-67a58cedb39a4e4f` | True | 0.800000 | 336.5 | 17386 | 4468 | None |
| 26 | `DOC-2c8bbcb1a7ca7668` | True | 0.400000 | 812.9 | 10084 | 2096 | None |
| 27 | `DOC-e29140d2e8e989be` | True | 0.400000 | 1193.5 | 32873 | 5508 | None |
| 28 | `DOC-e69313c4bb90489c` | True | 0.521700 | 1259.3 | 75514 | 15633 | None |
| 29 | `DOC-8cae10ecec1f5866` | True | 0.470600 | 1336.1 | 38406 | 9922 | None |
| 30 | `DOC-29c516a4775b07d9` | True | 0.769200 | 1478.7 | 70402 | 6629 | None |
