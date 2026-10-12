# Run report — `sand42-50-contracts-specialist-awq-1l4-c16`

Dated cell stem: `RUN-50-CONTRACTS-AWQ-1L4-C16`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `sand42-50-contracts-specialist-awq-1l4-c16` |
| task / agent | `contracts_specialist` |
| prompt | `contracts_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **1×L4** |
| concurrency | **16** |
| n | **50** |
| profile | `modal-vllm` |
| spec_hash | `630a7ebd89f0f3070416706fc458a10f4cc2d06f0ad0ab35eb06ccbe8b233c3d` |
| dataset fingerprint | `83eb6b1f2c7e` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **50 / 0 / 50** |
| **overall_extraction_score** | **0.542966** |
| schema_valid_rate | 1.000000 |
| error_count | 0 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 1011.997 |
| gpu_seconds | 1012.270 |
| estimated GPU cost | 0.224949 |
| **GPU $/doc** | **0.00449898** |
| latency p50 / max (s) | 176.201379 / 1109.377566 |
| prompt / completion tokens | 799423 / 132402 |
| concurrency speedup (Σlat/wall) | 14.44 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-f5a54932794ef16e` | True | 0.666700 | 97.3 | 5302 | 1021 | None |
| 2 | `DOC-6b4cc54c8c4d796f` | True | — | 103.5 | 4015 | 1075 | None |
| 3 | `DOC-b1aba7df0380a1b2` | True | — | 109.3 | 5032 | 1100 | None |
| 4 | `DOC-a9850db362f57916` | True | — | 115.1 | 6764 | 1128 | None |
| 5 | `DOC-fc9671ccde642e8d` | True | — | 127.1 | 7936 | 1242 | None |
| 6 | `DOC-3c07c9ccd9a01d6e` | True | 0.583300 | 142.2 | 7428 | 1369 | None |
| 7 | `DOC-385a86c69f8e562c` | True | 0.666700 | 153.6 | 6560 | 1536 | None |
| 8 | `DOC-e235bc9735f96335` | True | 0.500000 | 162.0 | 10699 | 1592 | None |
| 9 | `DOC-03529267ee75444d` | True | 0.727300 | 178.3 | 10583 | 1825 | None |
| 10 | `DOC-6671a684f52f82a9` | True | 0.571400 | 185.0 | 11320 | 1823 | None |
| 11 | `DOC-0812d9d3e2b1baa0` | True | 0.538500 | 208.9 | 18679 | 2165 | None |
| 12 | `DOC-593f2c6de770b84c` | True | 0.740700 | 219.0 | 9228 | 2298 | None |
| 13 | `DOC-f8b0d4bcbac60ca2` | True | 0.615400 | 109.2 | 3824 | 1260 | None |
| 14 | `DOC-e4272758b561f8cd` | True | 0.555600 | 137.2 | 6987 | 1485 | None |
| 15 | `DOC-81c4ce12d907380c` | True | 0.750000 | 122.3 | 7047 | 1365 | None |
| 16 | `DOC-9a36838df2878b37` | True | 0.538500 | 108.8 | 8142 | 1201 | None |
| 17 | `DOC-b83763aeff114369` | True | 0.529400 | 123.1 | 7446 | 1330 | None |
| 18 | `DOC-812192e392d8d410` | True | 0.600000 | 164.4 | 5551 | 1866 | None |
| 19 | `DOC-e998c563b82122b9` | True | 0.555600 | 115.0 | 10006 | 1270 | None |
| 20 | `DOC-035731e655e67aab` | True | 0.555600 | 141.1 | 5207 | 1488 | None |
| 21 | `DOC-70f90b46b2c4f1a6` | True | 0.571400 | 38.5 | 3154 | 460 | None |
| 22 | `DOC-27b649fe2f6fae8e` | True | 0.933300 | 114.7 | 5464 | 1327 | None |
| 23 | `DOC-4fb6419e37bff201` | True | 0.666700 | 445.4 | 22234 | 4698 | None |
| 24 | `DOC-1e22a2d4068b8650` | True | 0.714300 | 203.4 | 7587 | 2209 | None |
| 25 | `DOC-0752e0811f5f5eb7` | True | 0.303000 | 485.8 | 41619 | 5199 | None |
| 26 | `DOC-1ddc9333769d27e4` | True | 0.500000 | 116.3 | 4450 | 1367 | None |
| 27 | `DOC-8993ad1085e08bd0` | True | 0.594600 | 246.7 | 22402 | 2849 | None |
| 28 | `DOC-c9d4c4f8ff433527` | True | 0.500000 | 59.4 | 7730 | 729 | None |
| 29 | `DOC-186145066ab191fa` | True | 0.400000 | 86.8 | 3718 | 1022 | None |
| 30 | `DOC-472f423cdf0819ef` | True | 0.571400 | 107.2 | 4656 | 1304 | None |
| 31 | `DOC-dfb4e69a3ab10dc9` | True | 0.526300 | 174.1 | 7378 | 1917 | None |
| 32 | `DOC-fe06800cc62e5e19` | True | 0.666700 | 154.7 | 8619 | 1761 | None |
| 33 | `DOC-62b300182901e850` | True | 0.363600 | 277.6 | 33346 | 3009 | None |
| 34 | `DOC-9cee2e10b449a71c` | True | 0.764700 | 458.2 | 21752 | 5023 | None |
| 35 | `DOC-73055dbb1e9f5f2f` | True | 0.714300 | 509.3 | 49409 | 5489 | None |
| 36 | `DOC-f45b328fd8a54c8b` | True | 0.842100 | 86.8 | 4608 | 892 | None |
| 37 | `DOC-1266801f2faad19f` | True | 0.697700 | 660.0 | 33383 | 4965 | None |
| 38 | `DOC-01849fa3020a5ac1` | True | 0.500000 | 265.0 | 4173 | 1025 | None |
| 39 | `DOC-4b57f485708ab60b` | True | 0.600000 | 309.7 | 6639 | 1125 | None |
| 40 | `DOC-712c3f92a0a56b77` | True | 0.500000 | 680.8 | 56227 | 5163 | None |
| 41 | `DOC-2b510409d3b9a4a6` | True | 0.761900 | 809.6 | 21668 | 6822 | None |
| 42 | `DOC-dbe52fd78e44b0ef` | True | 0.769200 | 308.0 | 18750 | 1585 | None |
| 43 | `DOC-b87880882e5fe354` | True | — | 914.4 | 19278 | 5579 | None |
| 44 | `DOC-dfd20f94bb76b6e4` | True | 0.545500 | 346.6 | 21000 | 2357 | None |
| 45 | `DOC-e218d39bb2f3c5ef` | True | 0.500000 | 401.8 | 19923 | 3047 | None |
| 46 | `DOC-e0d31c39359cb803` | True | 0.378400 | 432.1 | 6879 | 3150 | None |
| 47 | `DOC-be1eccde5bae9c82` | True | 0.428600 | 410.4 | 9330 | 3349 | None |
| 48 | `DOC-8f737e9fec8f24f0` | True | 0.740700 | 606.2 | 35815 | 5348 | None |
| 49 | `DOC-53e364f030a30b5c` | True | 0.774200 | 973.7 | 94991 | 11638 | None |
| 50 | `DOC-e29140d2e8e989be` | True | 0.625000 | 1109.4 | 45485 | 8555 | None |
