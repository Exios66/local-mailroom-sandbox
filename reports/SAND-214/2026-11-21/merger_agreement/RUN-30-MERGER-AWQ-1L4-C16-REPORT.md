# Run report — `sand214-30-merger-specialist-awq-1l4-windows`

Dated cell stem: `RUN-30-MERGER-AWQ-1L4-C16`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `sand214-30-merger-specialist-awq-1l4-windows` |
| task / agent | `merger_agreement_specialist` |
| prompt | `merger_agreement_specialist_v4` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **1×L4** |
| concurrency | **16** |
| n | **30** |
| profile | `modal-vllm` |
| spec_hash | `3bad2758de0cc4e0f558d6f322e72f733b3935f439f1943e1f7bfe2beb0cb011` |
| dataset fingerprint | `cbcfe8810bbe` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **30 / 0 / 30** |
| **overall_extraction_score** | **0.091062** |
| schema_valid_rate | 1.000000 |
| error_count | 0 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 3778.160 |
| gpu_seconds | 3778.160 |
| estimated GPU cost | 0.839591 |
| **GPU $/doc** | **0.027986** |
| latency p50 / max (s) | 1062.209693 / 1749.907623 |
| prompt / completion tokens | 4217597 / 188911 |
| concurrency speedup (Σlat/wall) | 8.80 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-7d93372810daa57b` | True | 0 | 907.6 | 110339 | 4395 | None |
| 2 | `DOC-7430de65e5471741` | True | 0.157895 | 988.2 | 124389 | 4855 | None |
| 3 | `DOC-d9157f4ad78024e5` | True | 0 | 1008.0 | 129738 | 5037 | None |
| 4 | `DOC-42d38611a1408908` | True | 0.176471 | 1043.8 | 126594 | 5240 | None |
| 5 | `DOC-43fae061d598c311` | True | 0 | 1088.4 | 134962 | 5433 | None |
| 6 | `DOC-8d799df066c1ba2a` | True | 0 | 1100.2 | 146460 | 5527 | None |
| 7 | `DOC-5c4551264db0fe41` | True | 0 | 1125.1 | 147329 | 5571 | None |
| 8 | `DOC-7b30996a8b012214` | True | 0.111111 | 1133.4 | 130014 | 5681 | None |
| 9 | `DOC-511062d64bc9afc6` | True | 0 | 1177.9 | 150608 | 5835 | None |
| 10 | `DOC-c96b9c7e12f91576` | True | 0 | 1242.8 | 145514 | 6338 | None |
| 11 | `DOC-fc1b34a9d8c88140` | True | 0.125000 | 1363.4 | 144786 | 7077 | None |
| 12 | `DOC-d01014aed8ad8824` | True | 0.125000 | 1466.1 | 129686 | 7597 | None |
| 13 | `DOC-e8538f75b0f993e6` | True | 0.062500 | 1472.6 | 179560 | 7599 | None |
| 14 | `DOC-71bc59dd305ee8ed` | True | 0.076923 | 1488.6 | 169327 | 7665 | None |
| 15 | `DOC-ecf69d7e102ef62a` | True | 0.142857 | 1637.3 | 148199 | 8524 | None |
| 16 | `DOC-9420b777a4b0784c` | True | 0.235294 | 1749.9 | 151651 | 9129 | None |
| 17 | `DOC-bec74557186e9409` | True | 0.285714 | 949.6 | 125314 | 5451 | None |
| 18 | `DOC-0e26285e96267ad0` | True | 0.058824 | 1102.3 | 151013 | 6455 | None |
| 19 | `DOC-0534799ed39ca0db` | True | 0.055556 | 928.7 | 145852 | 5513 | None |
| 20 | `DOC-5c44797b6add60e4` | True | 0.066667 | 894.1 | 127212 | 5357 | None |
| 21 | `DOC-7e2818ceb0167d5a` | True | 0.166667 | 924.9 | 124828 | 5633 | None |
| 22 | `DOC-fd6090e354177e5b` | True | 0.277778 | 882.1 | 144741 | 5448 | None |
| 23 | `DOC-63beb09b179ea4ee` | True | 0.176471 | 1076.6 | 129968 | 6582 | None |
| 24 | `DOC-158ec6b697211e14` | True | 0.117647 | 1047.8 | 163880 | 6485 | None |
| 25 | `DOC-b3d0149fd994357a` | True | 0.117647 | 753.2 | 124896 | 4987 | None |
| 26 | `DOC-d1e355800bff0425` | True | 0.062500 | 917.5 | 142629 | 6669 | None |
| 27 | `DOC-3ddbb29c17f17312` | True | 0 | 704.0 | 126546 | 6006 | None |
| 28 | `DOC-ff3ceb691481f1bd` | True | 0.133333 | 756.1 | 144456 | 7012 | None |
| 29 | `DOC-7bd48ea19ade7399` | True | 0 | 964.3 | 113052 | 6764 | None |
| 30 | `DOC-f099c5c73d56631e` | True | 0 | 1337.2 | 184054 | 9046 | None |
