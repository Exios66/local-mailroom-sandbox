# Run report — `sand42-50-merger-specialist-awq-2l4-c32`

Dated cell stem: `RUN-50-MERGER-AWQ-2L4-C32`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `sand42-50-merger-specialist-awq-2l4-c32` |
| task / agent | `merger_agreement_specialist` |
| prompt | `merger_agreement_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **2×L4** |
| concurrency | **32** |
| n | **50** |
| profile | `modal-vllm` |
| spec_hash | `a96e6fbc7723e70b6791b0cc80dbf3a642d69d5e80343d13509bc338def6be2e` |
| dataset fingerprint | `aa4e596805e7` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **50 / 0 / 50** |
| **overall_extraction_score** | **0.024097** |
| schema_valid_rate | 1.000000 |
| error_count | 0 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 1972.327 |
| gpu_seconds | 1972.565 |
| estimated GPU cost | 0.876696 |
| **GPU $/doc** | **0.017534** |
| latency p50 / max (s) | 987.541598 / 1959.188491 |
| prompt / completion tokens | 4867606 / 311760 |
| concurrency speedup (Σlat/wall) | 25.99 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-bec74557186e9409` | True | 0 | 439.0 | 78918 | 4770 | None |
| 2 | `DOC-63beb09b179ea4ee` | True | 0.058824 | 580.0 | 83572 | 5467 | None |
| 3 | `DOC-dc7f18df501aec90` | True | 0 | 619.7 | 83008 | 4764 | None |
| 4 | `DOC-7e2818ceb0167d5a` | True | 0.055556 | 662.6 | 78432 | 4139 | None |
| 5 | `DOC-2b9f668ab6cb8901` | True | 0.052632 | 712.0 | 90831 | 4562 | None |
| 6 | `DOC-eb2b56fe30dc35f4` | True | 0 | 781.6 | 85298 | 4751 | None |
| 7 | `DOC-4f45bef14dcd1dbf` | True | 0.062500 | 781.8 | 70774 | 4117 | None |
| 8 | `DOC-30eda1e78a5f6fb5` | True | 0 | 798.2 | 107499 | 5809 | None |
| 9 | `DOC-f90cc5fb2ceac154` | True | 0 | 880.2 | 93747 | 4382 | None |
| 10 | `DOC-26933c93d649fa3f` | True | 0.062500 | 919.4 | 96354 | 4471 | None |
| 11 | `DOC-0a733ab86f2390ae` | True | 0 | 1021.2 | 81545 | 5041 | None |
| 12 | `DOC-72b0b8c8385edd48` | True | 0.055556 | 1027.0 | 84431 | 4372 | None |
| 13 | `DOC-9420b777a4b0784c` | True | 0 | 1050.6 | 98627 | 6040 | None |
| 14 | `DOC-1e016055aa435e71` | True | 0 | 1102.2 | 109137 | 6989 | None |
| 15 | `DOC-5f5d40f6b2c338ac` | True | 0 | 1136.1 | 109887 | 5080 | None |
| 16 | `DOC-c6b5f7ea5f718c28` | True | 0 | 1141.3 | 82765 | 5217 | None |
| 17 | `DOC-52f9a5be69429299` | True | 0.058824 | 1181.3 | 103918 | 9120 | None |
| 18 | `DOC-37bc3c44ae2c4ef6` | True | 0 | 1245.4 | 90012 | 6263 | None |
| 19 | `DOC-d4b1a7a2b981fbf4` | True | 0 | 1285.4 | 81817 | 5661 | None |
| 20 | `DOC-e8538f75b0f993e6` | True | 0 | 1354.1 | 113280 | 6935 | None |
| 21 | `DOC-297745a521cd1e8c` | True | 0 | 1355.4 | 103150 | 8588 | None |
| 22 | `DOC-0534799ed39ca0db` | True | 0.055556 | 1357.4 | 92828 | 7667 | None |
| 23 | `DOC-b03c0d2bbbb9659e` | True | 0 | 1394.1 | 113393 | 5383 | None |
| 24 | `DOC-fe9a8b51344d67d9` | True | 0 | 1394.0 | 130099 | 6948 | None |
| 25 | `DOC-882fabf7aba36941` | True | 0 | 1398.4 | 92325 | 6654 | None |
| 26 | `DOC-b3d0149fd994357a` | True | 0.058824 | 519.3 | 78500 | 4294 | None |
| 27 | `DOC-0070a4e34dddbfd5` | True | 0 | 727.5 | 85209 | 6591 | None |
| 28 | `DOC-c96b9c7e12f91576` | True | 0 | 1447.7 | 92490 | 6033 | None |
| 29 | `DOC-03712a2b0a99a314` | True | 0.058824 | 1021.8 | 119367 | 6805 | None |
| 30 | `DOC-ab5578f1f9f04244` | True | 0 | 1551.2 | 132059 | 8612 | None |
| 31 | `DOC-5f8ef95caa2fd349` | True | 0 | 1592.3 | 104105 | 9346 | None |
| 32 | `DOC-386ac6d669b7731c` | True | 0.076923 | 1593.5 | 93831 | 7563 | None |
| 33 | `DOC-9d34581755c603a3` | True | 0 | 816.8 | 94942 | 5906 | None |
| 34 | `DOC-fcaddb5bdc94ce63` | True | 0.058824 | 953.8 | 82656 | 4955 | None |
| 35 | `DOC-ac48214468deb8dd` | True | 0.058824 | 841.7 | 72887 | 5621 | None |
| 36 | `DOC-1cd38a83b224335d` | True | 0.058824 | 617.5 | 78294 | 4919 | None |
| 37 | `DOC-f449b47c7269f288` | True | 0.062500 | 572.0 | 95394 | 4471 | None |
| 38 | `DOC-ab735131c00271bc` | True | 0.055556 | 656.6 | 81228 | 4460 | None |
| 39 | `DOC-45f801408be08af6` | True | 0 | 1685.6 | 109920 | 11167 | None |
| 40 | `DOC-71bc59dd305ee8ed` | True | 0.076923 | 1711.3 | 109675 | 6728 | None |
| 41 | `DOC-f09307ad314d386f` | True | 0 | 579.9 | 103329 | 5740 | None |
| 42 | `DOC-e6c8852b877c4598` | True | 0.055556 | 937.1 | 104093 | 7836 | None |
| 43 | `DOC-ff3ceb691481f1bd` | True | 0 | 607.0 | 91432 | 6251 | None |
| 44 | `DOC-681bc6115b882191` | True | 0 | 576.2 | 120554 | 5970 | None |
| 45 | `DOC-23f224263f6974c5` | True | 0 | 526.1 | 83736 | 5277 | None |
| 46 | `DOC-26fa94f698c37fc5` | True | 0.058824 | 1195.7 | 79931 | 5997 | None |
| 47 | `DOC-f9870e3b8fd141b0` | True | 0 | 1167.8 | 134889 | 8463 | None |
| 48 | `DOC-169bbcdc5d9e609c` | True | 0 | 938.5 | 134911 | 7562 | None |
| 49 | `DOC-5d30efc302f3c431` | True | 0.062500 | 855.8 | 130943 | 11157 | None |
| 50 | `DOC-511062d64bc9afc6` | True | 0 | 1959.2 | 97584 | 6846 | None |
