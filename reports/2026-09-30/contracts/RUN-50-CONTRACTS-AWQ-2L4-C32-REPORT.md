# Run report — `grid-50-contracts-specialist-awq-2l4`

Dated cell stem: `RUN-50-CONTRACTS-AWQ-2L4-C32`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `grid-50-contracts-specialist-awq-2l4` |
| task / agent | `contracts_specialist` |
| prompt | `contracts_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **2×L4** |
| concurrency | **32** |
| n | **50** |
| profile | `modal-vllm` |
| spec_hash | `3d6cf80c3f4d141084841300fdd6874a4329831c8b56bdfb8a9f243de4d44302` |
| dataset fingerprint | `c29633d769b5` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **48 / 2 / 50** |
| **overall_extraction_score** | **0.515185** |
| schema_valid_rate | 1.000000 |
| error_count | 2 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 329.826 |
| gpu_seconds | 329.826 |
| estimated GPU cost | 0.146589 |
| **GPU $/doc** | **0.00305394** |
| latency p50 / max (s) | 132.881100 / 258.417006 |
| prompt / completion tokens | 352894 / 82067 |
| concurrency speedup (Σlat/wall) | 19.01 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-98ff556893f1a98f` | True | 0.857100 | 42.5 | 3200 | 324 | None |
| 2 | `DOC-83320eec5eec6235` | True | 0.666700 | 47.0 | 7706 | 945 | None |
| 3 | `DOC-9696c5996f24d85d` | True | — | 50.7 | 4377 | 1065 | None |
| 4 | `DOC-ea746c407db93af2` | True | — | 50.9 | 4804 | 1065 | None |
| 5 | `DOC-2e3e2bb13d6c83ca` | True | — | 59.4 | 13464 | 597 | None |
| 6 | `DOC-6712aa595cfe3e2c` | True | 0.555600 | 67.7 | 7666 | 1441 | None |
| 7 | `DOC-adad5ef793c0e409` | True | 0.518500 | 67.9 | 8247 | 1441 | None |
| 8 | `DOC-440a54573c24b918` | True | 0.800000 | 98.5 | 3493 | 1250 | None |
| 9 | `DOC-15262384b17086bb` | True | 0.709700 | 98.7 | 8178 | 2267 | None |
| 10 | `DOC-770401d1d47fd744` | True | 0.642900 | 104.8 | 7751 | 1339 | None |
| 11 | `DOC-55df050fcb737129` | True | 0.588200 | 104.9 | 5461 | 1329 | None |
| 12 | `DOC-8a776dec500b074c` | True | 0.344800 | 53.4 | 8308 | 1284 | None |
| 13 | `DOC-4be26020b0470e43` | True | 0.545500 | 113.2 | 7501 | 1427 | None |
| 14 | `DOC-d66d8f6c92207c3c` | True | 0.666700 | 115.4 | 4746 | 1442 | None |
| 15 | `DOC-c68a4dd90660c113` | True | 0.615400 | 79.1 | 7851 | 1814 | None |
| 16 | `DOC-fca31a55b1d526ea` | True | 0.833300 | 133.3 | 5459 | 3034 | None |
| 17 | `DOC-03f1f6c0db99e651` | True | 0.500000 | 83.4 | 7683 | 1975 | None |
| 18 | `DOC-f717fb61aa615da0` | True | 0.500000 | 135.4 | 8165 | 1748 | None |
| 19 | `DOC-25f822c661011bfe` | True | 0.437500 | 138.3 | 7821 | 1776 | None |
| 20 | `DOC-4ab8d1d37d3af05c` | True | 0.615400 | 83.3 | 7678 | 2039 | None |
| 21 | `DOC-5892b6dc609c8d0f` | True | — | 151.4 | 7606 | 1951 | None |
| 22 | `DOC-ba6d7a0ea5100bbb` | True | 0.666700 | 153.7 | 7887 | 1621 | None |
| 23 | `DOC-54ad252b1e5e8d58` | True | 0.774200 | 159.6 | 8244 | 2051 | None |
| 24 | `DOC-9a2c7cc21a860fc4` | True | 0.714300 | 60.9 | 7027 | 1525 | None |
| 25 | `DOC-d1c45d175a8abeb5` | True | 0.714300 | 31.7 | 6851 | 875 | None |
| 26 | `DOC-c2ac5762c7f227fa` | True | — | 171.5 | 8143 | 2245 | None |
| 27 | `DOC-c7f557969d953fae` | True | — | 176.7 | 8119 | 2279 | None |
| 28 | `DOC-c30c293d38a2cd8b` | True | 0.720000 | 177.6 | 9794 | 835 | None |
| 29 | `DOC-0de76b97986b57b3` | True | 0.588200 | 83.8 | 7735 | 2189 | None |
| 30 | `DOC-9e063c6e3baf1233` | True | 0.571400 | 186.8 | 7486 | 2434 | None |
| 31 | `DOC-99ca00712a84f039` | True | 0.571400 | 190.8 | 5337 | 2463 | None |
| 32 | `DOC-e492894fbfa36087` | True | 0.666700 | 81.9 | 8030 | 2316 | None |
| 33 | `DOC-06229aa6571f9d46` | True | 0.625000 | 132.5 | 6154 | 635 | None |
| 34 | `DOC-9b569749ea3d6f42` | True | — | 206.7 | 11640 | 2101 | None |
| 35 | `DOC-09c0c774c3e5ec74` | True | 0.645200 | 220.6 | 8507 | 1740 | None |
| 36 | `DOC-ade03c57c5f78e21` | True | 0.923100 | 227.9 | 4093 | 1722 | None |
| 37 | `DOC-a2ce7adbf6f5cb8d` | True | 0.594600 | 114.5 | 6729 | 3559 | None |
| 38 | `DOC-962cc639f3ebee80` | True | — | 233.2 | 7359 | 1917 | None |
| 39 | `DOC-364e40f0752551a3` | True | 0.444400 | 140.3 | 10159 | 1261 | None |
| 40 | `DOC-f9b36fee351217c2` | True | 0.555600 | 195.9 | 7931 | 1582 | None |
| 41 | `DOC-ee4369c8980926dc` | True | 0.533300 | 249.2 | 7993 | 1846 | None |
| 42 | `DOC-2ca7b08d2d439f1e` | True | — | 258.4 | 7616 | 2511 | None |
| 43 | `DOC-561364d531fca179` | True | 0.600000 | 128.1 | 7519 | 1504 | None |
| 44 | `DOC-e853a8ab86c5a54d` | True | 0.761900 | 163.0 | 4692 | 1888 | None |
| 45 | `DOC-dfa5c8eb1e7b837c` | True | 0.909100 | 150.4 | 6055 | 1703 | None |
| 46 | `DOC-f333c4b8048d5d8c` | True | 0.631600 | 142.1 | 7940 | 1700 | None |
| 47 | `DOC-93e9bb030e2b282d` | True | 0.650000 | 217.8 | 8560 | 2262 | None |
| 48 | `DOC-01633b99e74dc9f2` | True | 0.470600 | 134.4 | 8129 | 1750 | None |
| 49 | `DOC-e235bc9735f96335` | False | — | 283.2 | — | — | LengthFinishReasonError: Could not parse response content as the length limit was reached - CompletionUsage(completion_tokens=8192, prompt_tokens=7449, total_tokens=15641, completion_tokens_details=None, prompt_tokens_details=None) |
| 50 | `DOC-34904aee099a62c7` | False | — | 372.3 | — | — | LengthFinishReasonError: Could not parse response content as the length limit was reached - CompletionUsage(completion_tokens=8192, prompt_tokens=6946, total_tokens=15138, completion_tokens_details=None, prompt_tokens_details=None) |
