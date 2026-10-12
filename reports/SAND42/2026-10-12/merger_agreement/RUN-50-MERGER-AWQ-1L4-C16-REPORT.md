# Run report — `sand42-50-merger-specialist-awq-1l4-c16`

Dated cell stem: `RUN-50-MERGER-AWQ-1L4-C16`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `sand42-50-merger-specialist-awq-1l4-c16` |
| task / agent | `merger_agreement_specialist` |
| prompt | `merger_agreement_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **1×L4** |
| concurrency | **16** |
| n | **50** |
| profile | `modal-vllm` |
| spec_hash | `29ddbe9d7946d23eace974e2a75e18e764b809b64a1b5ffa049b85cb5e3c7b0c` |
| dataset fingerprint | `aa4e596805e7` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **50 / 0 / 50** |
| **overall_extraction_score** | **0.028958** |
| schema_valid_rate | 1.000000 |
| error_count | 0 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 3100.735 |
| gpu_seconds | 3101.109 |
| estimated GPU cost | 0.689135 |
| **GPU $/doc** | **0.013783** |
| latency p50 / max (s) | 1045.555791 / 2405.978605 |
| prompt / completion tokens | 4867606 / 304542 |
| concurrency speedup (Σlat/wall) | 18.73 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-30eda1e78a5f6fb5` | True | 0 | 982.4 | 107499 | 11510 | None |
| 2 | `DOC-d4b1a7a2b981fbf4` | True | 0.117647 | 1192.4 | 81817 | 4038 | None |
| 3 | `DOC-882fabf7aba36941` | True | 0 | 1369.9 | 92325 | 4188 | None |
| 4 | `DOC-dc7f18df501aec90` | True | 0.066667 | 1421.8 | 83008 | 4440 | None |
| 5 | `DOC-4f45bef14dcd1dbf` | True | 0.062500 | 1444.6 | 70774 | 3807 | None |
| 6 | `DOC-0a733ab86f2390ae` | True | 0.066667 | 1482.2 | 81545 | 5091 | None |
| 7 | `DOC-26933c93d649fa3f` | True | 0 | 1494.7 | 96354 | 5000 | None |
| 8 | `DOC-eb2b56fe30dc35f4` | True | 0.058824 | 1533.4 | 85298 | 5396 | None |
| 9 | `DOC-9420b777a4b0784c` | True | 0 | 1553.1 | 98627 | 5433 | None |
| 10 | `DOC-c96b9c7e12f91576` | True | 0 | 1568.3 | 92490 | 5517 | None |
| 11 | `DOC-52f9a5be69429299` | True | 0 | 1650.9 | 103918 | 6158 | None |
| 12 | `DOC-45f801408be08af6` | True | 0.133333 | 1739.9 | 109920 | 6615 | None |
| 13 | `DOC-e8538f75b0f993e6` | True | 0 | 1799.5 | 113280 | 7115 | None |
| 14 | `DOC-71bc59dd305ee8ed` | True | 0.076923 | 1891.2 | 109675 | 7660 | None |
| 15 | `DOC-511062d64bc9afc6` | True | 0 | 1180.8 | 97584 | 7550 | None |
| 16 | `DOC-5f5d40f6b2c338ac` | True | 0 | 2164.4 | 109887 | 7774 | None |
| 17 | `DOC-ab5578f1f9f04244` | True | 0.066667 | 1055.1 | 132059 | 6681 | None |
| 18 | `DOC-f90cc5fb2ceac154` | True | 0 | 843.1 | 93747 | 5491 | None |
| 19 | `DOC-63beb09b179ea4ee` | True | 0.058824 | 781.9 | 83572 | 5057 | None |
| 20 | `DOC-bec74557186e9409` | True | 0 | 827.2 | 78918 | 5307 | None |
| 21 | `DOC-1e016055aa435e71` | True | 0 | 927.7 | 109137 | 5923 | None |
| 22 | `DOC-b03c0d2bbbb9659e` | True | 0 | 2406.0 | 113393 | 4854 | None |
| 23 | `DOC-5f8ef95caa2fd349` | True | 0 | 1043.0 | 104105 | 6600 | None |
| 24 | `DOC-2b9f668ab6cb8901` | True | 0.052632 | 847.0 | 90831 | 5285 | None |
| 25 | `DOC-c6b5f7ea5f718c28` | True | 0.058824 | 767.4 | 82765 | 4799 | None |
| 26 | `DOC-0534799ed39ca0db` | True | 0 | 1031.0 | 92828 | 6470 | None |
| 27 | `DOC-37bc3c44ae2c4ef6` | True | 0 | 1048.1 | 90012 | 6529 | None |
| 28 | `DOC-fe9a8b51344d67d9` | True | 0.083333 | 1212.3 | 130099 | 7517 | None |
| 29 | `DOC-386ac6d669b7731c` | True | 0.076923 | 1004.6 | 93831 | 6068 | None |
| 30 | `DOC-fcaddb5bdc94ce63` | True | 0 | 638.5 | 82656 | 3782 | None |
| 31 | `DOC-297745a521cd1e8c` | True | 0 | 1266.4 | 103150 | 7805 | None |
| 32 | `DOC-72b0b8c8385edd48` | True | 0.055556 | 867.3 | 84431 | 5196 | None |
| 33 | `DOC-ac48214468deb8dd` | True | 0.058824 | 836.5 | 72887 | 5002 | None |
| 34 | `DOC-1cd38a83b224335d` | True | 0.058824 | 642.5 | 78294 | 3890 | None |
| 35 | `DOC-03712a2b0a99a314` | True | 0 | 1017.1 | 119367 | 5985 | None |
| 36 | `DOC-b3d0149fd994357a` | True | 0 | 724.4 | 78500 | 4423 | None |
| 37 | `DOC-f9870e3b8fd141b0` | True | 0 | 1066.1 | 134889 | 6523 | None |
| 38 | `DOC-9d34581755c603a3` | True | 0 | 866.1 | 94942 | 5369 | None |
| 39 | `DOC-ab735131c00271bc` | True | 0.055556 | 745.0 | 81228 | 5032 | None |
| 40 | `DOC-f449b47c7269f288` | True | 0.062500 | 550.2 | 95394 | 3862 | None |
| 41 | `DOC-169bbcdc5d9e609c` | True | 0 | 1023.4 | 134911 | 7092 | None |
| 42 | `DOC-0070a4e34dddbfd5` | True | 0 | 1241.8 | 85209 | 8642 | None |
| 43 | `DOC-ff3ceb691481f1bd` | True | 0 | 637.2 | 91432 | 5337 | None |
| 44 | `DOC-5d30efc302f3c431` | True | 0.062500 | 850.6 | 130943 | 7341 | None |
| 45 | `DOC-681bc6115b882191` | True | 0 | 527.1 | 120554 | 5602 | None |
| 46 | `DOC-26fa94f698c37fc5` | True | 0.058824 | 1522.7 | 79931 | 5824 | None |
| 47 | `DOC-f09307ad314d386f` | True | 0 | 791.6 | 103329 | 7735 | None |
| 48 | `DOC-23f224263f6974c5` | True | 0 | 568.5 | 83736 | 7104 | None |
| 49 | `DOC-7e2818ceb0167d5a` | True | 0.055556 | 1763.6 | 78432 | 4543 | None |
| 50 | `DOC-e6c8852b877c4598` | True | 0 | 1670.2 | 104093 | 14580 | None |
