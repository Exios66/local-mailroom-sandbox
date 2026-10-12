# Run report — `sand42-50-merger-specialist-awq-2l4-c8`

Dated cell stem: `RUN-50-MERGER-AWQ-2L4-C8`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `sand42-50-merger-specialist-awq-2l4-c8` |
| task / agent | `merger_agreement_specialist` |
| prompt | `merger_agreement_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **2×L4** |
| concurrency | **8** |
| n | **50** |
| profile | `modal-vllm` |
| spec_hash | `b1dc72159d3e4d3c593caf3a5c475284848e615d4b6fb599238734980951611a` |
| dataset fingerprint | `aa4e596805e7` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **50 / 0 / 50** |
| **overall_extraction_score** | **0.030960** |
| schema_valid_rate | 1.000000 |
| error_count | 0 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 3185.974 |
| gpu_seconds | 3186.354 |
| estimated GPU cost | 1.416157 |
| **GPU $/doc** | **0.028323** |
| latency p50 / max (s) | 389.655693 / 1075.386142 |
| prompt / completion tokens | 4867606 / 301770 |
| concurrency speedup (Σlat/wall) | 7.27 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-0a733ab86f2390ae` | True | 0.066667 | 266.8 | 81545 | 3938 | None |
| 2 | `DOC-eb2b56fe30dc35f4` | True | 0 | 284.3 | 85298 | 4465 | None |
| 3 | `DOC-5f5d40f6b2c338ac` | True | 0 | 296.0 | 109887 | 4588 | None |
| 4 | `DOC-26933c93d649fa3f` | True | 0.062500 | 305.7 | 96354 | 5774 | None |
| 5 | `DOC-c96b9c7e12f91576` | True | 0 | 363.4 | 92490 | 5861 | None |
| 6 | `DOC-d4b1a7a2b981fbf4` | True | 0.058824 | 399.5 | 81817 | 6085 | None |
| 7 | `DOC-4f45bef14dcd1dbf` | True | 0.062500 | 234.2 | 70774 | 4363 | None |
| 8 | `DOC-52f9a5be69429299` | True | 0 | 308.0 | 103918 | 5639 | None |
| 9 | `DOC-dc7f18df501aec90` | True | 0 | 605.9 | 83008 | 4020 | None |
| 10 | `DOC-b03c0d2bbbb9659e` | True | 0 | 304.9 | 113393 | 5267 | None |
| 11 | `DOC-9420b777a4b0784c` | True | 0 | 389.4 | 98627 | 6655 | None |
| 12 | `DOC-45f801408be08af6` | True | 0 | 737.6 | 109920 | 6894 | None |
| 13 | `DOC-e8538f75b0f993e6` | True | 0 | 389.9 | 113280 | 7349 | None |
| 14 | `DOC-882fabf7aba36941` | True | 0 | 292.9 | 92325 | 5217 | None |
| 15 | `DOC-30eda1e78a5f6fb5` | True | 0 | 366.4 | 107499 | 6381 | None |
| 16 | `DOC-bec74557186e9409` | True | 0 | 202.8 | 78918 | 5162 | None |
| 17 | `DOC-5f8ef95caa2fd349` | True | 0 | 390.8 | 104105 | 6823 | None |
| 18 | `DOC-ab5578f1f9f04244` | True | 0.200000 | 445.2 | 132059 | 7311 | None |
| 19 | `DOC-71bc59dd305ee8ed` | True | 0.076923 | 729.3 | 109675 | 6371 | None |
| 20 | `DOC-f90cc5fb2ceac154` | True | 0 | 377.4 | 93747 | 6526 | None |
| 21 | `DOC-63beb09b179ea4ee` | True | 0.058824 | 283.9 | 83572 | 5020 | None |
| 22 | `DOC-511062d64bc9afc6` | True | 0 | 707.4 | 97584 | 5749 | None |
| 23 | `DOC-0534799ed39ca0db` | True | 0 | 305.1 | 92828 | 5537 | None |
| 24 | `DOC-37bc3c44ae2c4ef6` | True | 0 | 388.9 | 90012 | 6881 | None |
| 25 | `DOC-fe9a8b51344d67d9` | True | 0 | 441.0 | 130099 | 7733 | None |
| 26 | `DOC-1e016055aa435e71` | True | 0 | 679.9 | 109137 | 5805 | None |
| 27 | `DOC-c6b5f7ea5f718c28` | True | 0.117647 | 252.9 | 82765 | 3937 | None |
| 28 | `DOC-2b9f668ab6cb8901` | True | 0.052632 | 402.7 | 90831 | 7581 | None |
| 29 | `DOC-297745a521cd1e8c` | True | 0 | 531.9 | 103150 | 9294 | None |
| 30 | `DOC-72b0b8c8385edd48` | True | 0.055556 | 295.0 | 84431 | 4419 | None |
| 31 | `DOC-386ac6d669b7731c` | True | 0.076923 | 388.3 | 93831 | 6697 | None |
| 32 | `DOC-26fa94f698c37fc5` | True | 0.058824 | 314.1 | 79931 | 5418 | None |
| 33 | `DOC-f9870e3b8fd141b0` | True | 0 | 396.6 | 134889 | 7636 | None |
| 34 | `DOC-ac48214468deb8dd` | True | 0.058824 | 266.1 | 72887 | 4961 | None |
| 35 | `DOC-7e2818ceb0167d5a` | True | 0.111111 | 486.9 | 78432 | 4425 | None |
| 36 | `DOC-0070a4e34dddbfd5` | True | 0 | 382.0 | 85209 | 7153 | None |
| 37 | `DOC-e6c8852b877c4598` | True | 0 | 394.3 | 104093 | 6952 | None |
| 38 | `DOC-fcaddb5bdc94ce63` | True | 0.058824 | 654.0 | 82656 | 5177 | None |
| 39 | `DOC-b3d0149fd994357a` | True | 0.058824 | 256.8 | 78500 | 4896 | None |
| 40 | `DOC-9d34581755c603a3` | True | 0 | 405.9 | 94942 | 7255 | None |
| 41 | `DOC-03712a2b0a99a314` | True | 0 | 729.8 | 119367 | 6876 | None |
| 42 | `DOC-1cd38a83b224335d` | True | 0.058824 | 326.1 | 78294 | 5167 | None |
| 43 | `DOC-169bbcdc5d9e609c` | True | 0.076923 | 417.7 | 134911 | 7417 | None |
| 44 | `DOC-ab735131c00271bc` | True | 0.055556 | 295.1 | 81228 | 5234 | None |
| 45 | `DOC-f09307ad314d386f` | True | 0.058824 | 863.8 | 103329 | 5748 | None |
| 46 | `DOC-f449b47c7269f288` | True | 0 | 891.4 | 95394 | 6237 | None |
| 47 | `DOC-ff3ceb691481f1bd` | True | 0 | 855.8 | 91432 | 4853 | None |
| 48 | `DOC-681bc6115b882191` | True | 0 | 926.8 | 120554 | 6667 | None |
| 49 | `DOC-23f224263f6974c5` | True | 0 | 869.8 | 83736 | 6026 | None |
| 50 | `DOC-5d30efc302f3c431` | True | 0.062500 | 1075.4 | 130943 | 10330 | None |
