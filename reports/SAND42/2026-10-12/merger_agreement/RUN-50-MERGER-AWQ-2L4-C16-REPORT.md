# Run report — `sand42-50-merger-specialist-awq-2l4-c16`

Dated cell stem: `RUN-50-MERGER-AWQ-2L4-C16`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `sand42-50-merger-specialist-awq-2l4-c16` |
| task / agent | `merger_agreement_specialist` |
| prompt | `merger_agreement_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **2×L4** |
| concurrency | **16** |
| n | **50** |
| profile | `modal-vllm` |
| spec_hash | `5fdbc7606f490b5d2e2633ba9241577ed4329009af72d4984a623dbac8facc0d` |
| dataset fingerprint | `aa4e596805e7` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **50 / 0 / 50** |
| **overall_extraction_score** | **0.023653** |
| schema_valid_rate | 1.000000 |
| error_count | 0 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 2866.639 |
| gpu_seconds | 2866.918 |
| estimated GPU cost | 1.274186 |
| **GPU $/doc** | **0.025484** |
| latency p50 / max (s) | 605.147577 / 2036.552925 |
| prompt / completion tokens | 4867606 / 299988 |
| concurrency speedup (Σlat/wall) | 13.66 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-0a733ab86f2390ae` | True | 0.133333 | 361.8 | 81545 | 4231 | None |
| 2 | `DOC-4f45bef14dcd1dbf` | True | 0.062500 | 404.4 | 70774 | 4473 | None |
| 3 | `DOC-eb2b56fe30dc35f4` | True | 0.058824 | 411.9 | 85298 | 4548 | None |
| 4 | `DOC-5f5d40f6b2c338ac` | True | 0 | 440.5 | 109887 | 5604 | None |
| 5 | `DOC-d4b1a7a2b981fbf4` | True | 0.058824 | 497.8 | 81817 | 5563 | None |
| 6 | `DOC-e8538f75b0f993e6` | True | 0 | 554.8 | 113280 | 6322 | None |
| 7 | `DOC-26933c93d649fa3f` | True | 0 | 573.5 | 96354 | 5635 | None |
| 8 | `DOC-dc7f18df501aec90` | True | 0 | 589.4 | 83008 | 5823 | None |
| 9 | `DOC-c96b9c7e12f91576` | True | 0 | 594.2 | 92490 | 6330 | None |
| 10 | `DOC-71bc59dd305ee8ed` | True | 0.076923 | 697.2 | 109675 | 9846 | None |
| 11 | `DOC-52f9a5be69429299` | True | 0 | 711.7 | 103918 | 6922 | None |
| 12 | `DOC-30eda1e78a5f6fb5` | True | 0 | 749.6 | 107499 | 6707 | None |
| 13 | `DOC-b03c0d2bbbb9659e` | True | 0 | 809.7 | 113393 | 8205 | None |
| 14 | `DOC-511062d64bc9afc6` | True | 0 | 499.9 | 97584 | 5178 | None |
| 15 | `DOC-1e016055aa435e71` | True | 0 | 467.7 | 109137 | 6266 | None |
| 16 | `DOC-37bc3c44ae2c4ef6` | True | 0 | 930.1 | 90012 | 5683 | None |
| 17 | `DOC-f90cc5fb2ceac154` | True | 0 | 1196.4 | 93747 | 6964 | None |
| 18 | `DOC-0534799ed39ca0db` | True | 0 | 1109.8 | 92828 | 5957 | None |
| 19 | `DOC-5f8ef95caa2fd349` | True | 0 | 1293.1 | 104105 | 7992 | None |
| 20 | `DOC-ab5578f1f9f04244` | True | 0 | 1311.7 | 132059 | 8691 | None |
| 21 | `DOC-bec74557186e9409` | True | 0 | 1172.9 | 78918 | 5326 | None |
| 22 | `DOC-9420b777a4b0784c` | True | 0 | 1742.0 | 98627 | 5736 | None |
| 23 | `DOC-fe9a8b51344d67d9` | True | 0 | 1152.6 | 130099 | 6891 | None |
| 24 | `DOC-c6b5f7ea5f718c28` | True | 0 | 970.5 | 82765 | 4644 | None |
| 25 | `DOC-297745a521cd1e8c` | True | 0 | 1081.2 | 103150 | 7532 | None |
| 26 | `DOC-386ac6d669b7731c` | True | 0.076923 | 1040.4 | 93831 | 4997 | None |
| 27 | `DOC-45f801408be08af6` | True | 0 | 1947.9 | 109920 | 8358 | None |
| 28 | `DOC-882fabf7aba36941` | True | 0 | 2036.6 | 92325 | 7169 | None |
| 29 | `DOC-63beb09b179ea4ee` | True | 0.058824 | 1479.6 | 83572 | 5397 | None |
| 30 | `DOC-72b0b8c8385edd48` | True | 0.055556 | 1108.7 | 84431 | 5535 | None |
| 31 | `DOC-fcaddb5bdc94ce63` | True | 0.058824 | 361.5 | 82656 | 4177 | None |
| 32 | `DOC-26fa94f698c37fc5` | True | 0.058824 | 388.9 | 79931 | 4441 | None |
| 33 | `DOC-ac48214468deb8dd` | True | 0.058824 | 384.5 | 72887 | 4330 | None |
| 34 | `DOC-0070a4e34dddbfd5` | True | 0 | 459.5 | 85209 | 5004 | None |
| 35 | `DOC-9d34581755c603a3` | True | 0 | 426.6 | 94942 | 4982 | None |
| 36 | `DOC-2b9f668ab6cb8901` | True | 0.052632 | 1545.3 | 90831 | 5570 | None |
| 37 | `DOC-1cd38a83b224335d` | True | 0 | 309.1 | 78294 | 3481 | None |
| 38 | `DOC-e6c8852b877c4598` | True | 0.055556 | 563.8 | 104093 | 6809 | None |
| 39 | `DOC-b3d0149fd994357a` | True | 0.058824 | 437.2 | 78500 | 5818 | None |
| 40 | `DOC-ab735131c00271bc` | True | 0 | 323.0 | 81228 | 4416 | None |
| 41 | `DOC-f9870e3b8fd141b0` | True | 0 | 661.4 | 134889 | 7406 | None |
| 42 | `DOC-169bbcdc5d9e609c` | True | 0.076923 | 538.1 | 134911 | 6449 | None |
| 43 | `DOC-f449b47c7269f288` | True | 0.062500 | 369.8 | 95394 | 4907 | None |
| 44 | `DOC-7e2818ceb0167d5a` | True | 0.055556 | 850.2 | 78432 | 5151 | None |
| 45 | `DOC-f09307ad314d386f` | True | 0 | 406.6 | 103329 | 6486 | None |
| 46 | `DOC-03712a2b0a99a314` | True | 0 | 903.7 | 119367 | 5692 | None |
| 47 | `DOC-5d30efc302f3c431` | True | 0.062500 | 525.0 | 130943 | 7902 | None |
| 48 | `DOC-23f224263f6974c5` | True | 0 | 401.9 | 83736 | 7148 | None |
| 49 | `DOC-681bc6115b882191` | True | 0 | 616.1 | 120554 | 5715 | None |
| 50 | `DOC-ff3ceb691481f1bd` | True | 0 | 759.3 | 91432 | 5579 | None |
