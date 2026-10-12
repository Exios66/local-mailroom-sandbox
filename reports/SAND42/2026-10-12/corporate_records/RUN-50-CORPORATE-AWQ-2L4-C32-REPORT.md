# Run report — `sand42-50-corporate-records-specialist-awq-2l4-c32`

Dated cell stem: `RUN-50-CORPORATE-AWQ-2L4-C32`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `sand42-50-corporate-records-specialist-awq-2l4-c32` |
| task / agent | `corporate_records_specialist` |
| prompt | `corporate_records_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **2×L4** |
| concurrency | **32** |
| n | **50** |
| profile | `modal-vllm` |
| spec_hash | `4c3e1631dfa8dc7584a9fccf13250c79f4a07bbdbf8cb9147a38a44b5784108a` |
| dataset fingerprint | `76b083c7c46d` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **50 / 0 / 50** |
| **overall_extraction_score** | **0.485094** |
| schema_valid_rate | 0.960000 |
| error_count | 0 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 49.069 |
| gpu_seconds | 49.396 |
| estimated GPU cost | 0.021954 |
| **GPU $/doc** | **0.00043908** |
| latency p50 / max (s) | 19.107101 / 33.994315 |
| prompt / completion tokens | 197319 / 7970 |
| concurrency speedup (Σlat/wall) | 20.04 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-f134b9491efc5c57` | True | 0.794900 | 14.1 | 2865 | 140 | None |
| 2 | `DOC-e077f1f7e80e1e04` | True | 0.162400 | 14.1 | 4043 | 151 | None |
| 3 | `DOC-474a0002b4c03be1` | True | 0.820500 | 14.2 | 2938 | 150 | None |
| 4 | `DOC-b832b5eaa2b4848c` | True | 0.106800 | 14.3 | 2762 | 157 | None |
| 5 | `DOC-01054efd0980066b` | True | 0.822200 | 14.5 | 5122 | 159 | None |
| 6 | `DOC-fbcdd16e24f143ac` | True | 0.158200 | 14.5 | 2456 | 155 | None |
| 7 | `DOC-0f56fe8db6df01bd` | True | 0.063500 | 14.5 | 5368 | 161 | None |
| 8 | `DOC-e545bbd5f5ea61b6` | True | 0.363600 | 14.7 | 2788 | 159 | None |
| 9 | `DOC-020d77c0107d273d` | True | 0.474600 | 17.6 | 2302 | 113 | None |
| 10 | `DOC-9376c6bfa6779d5e` | True | 0.482200 | 17.8 | 2200 | 131 | None |
| 11 | `DOC-2f19002c84083aa8` | True | 0.495100 | 19.1 | 5200 | 170 | None |
| 12 | `DOC-68d5a8753fcc3675` | True | 0.440500 | 19.1 | 5671 | 177 | None |
| 13 | `DOC-c4c9c37a96291975` | True | 0.081300 | 19.4 | 2424 | 136 | None |
| 14 | `DOC-9ca44c7926a47ede` | True | 0.502400 | 19.7 | 2292 | 131 | None |
| 15 | `DOC-b3ad98e5530dfeaf` | True | 0.282000 | 19.5 | 2521 | 189 | None |
| 16 | `DOC-a5fd7fe18b094f20` | True | 0.848500 | 21.4 | 5919 | 145 | None |
| 17 | `DOC-6790430ae2a6c724` | True | 0.184600 | 22.5 | 4477 | 142 | None |
| 18 | `DOC-12a6d4cd092cf66d` | True | 0.502600 | 23.1 | 7710 | 158 | None |
| 19 | `DOC-81ae205a3b0bf16f` | True | 0.248000 | 23.5 | 2515 | 158 | None |
| 20 | `DOC-9467462d9bb34f8e` | True | 0.541700 | 23.3 | 5345 | 158 | None |
| 21 | `DOC-0a262afc80c73247` | True | 0.113600 | 25.4 | 3124 | 156 | None |
| 22 | `DOC-732b812b7d9d9653` | True | 0.888900 | 25.4 | 5572 | 165 | None |
| 23 | `DOC-d015968793450753` | True | 0.805600 | 27.0 | 5082 | 166 | None |
| 24 | `DOC-bfa92eb6c72569ee` | True | 0.118400 | 13.5 | 3771 | 158 | None |
| 25 | `DOC-4dc719baa790a79c` | True | 0.666700 | 27.7 | 2669 | 167 | None |
| 26 | `DOC-0a8eb16fff7e67ca` | True | 0.359000 | 13.4 | 5246 | 159 | None |
| 27 | `DOC-e6906e59f9bd74ca` | True | 0.620000 | 10.0 | 2978 | 160 | None |
| 28 | `DOC-80e90a37bb750a3c` | True | 0.149500 | 13.5 | 2776 | 167 | None |
| 29 | `DOC-606242f2919653a4` | True | 0.233200 | 9.0 | 5253 | 160 | None |
| 30 | `DOC-dfe42f3747f299e6` | True | 0.750000 | 7.3 | 5870 | 158 | None |
| 31 | `DOC-d4dfbfe8049d41f9` | True | 0.493400 | 9.7 | 3856 | 175 | None |
| 32 | `DOC-27bbad54b6fd107e` | True | 0.833300 | 6.5 | 2871 | 182 | None |
| 33 | `DOC-a973ebf005e0e785` | True | 0.427800 | 15.4 | 6146 | 234 | None |
| 34 | `DOC-fc9f56d999bd7566` | True | 0.666700 | 30.1 | 2509 | 184 | None |
| 35 | `DOC-1e8e3ce47882ae71` | True | 0.148500 | 30.8 | 3063 | 198 | None |
| 36 | `DOC-41b53ea487b84955` | True | 0.750000 | 32.1 | 4617 | 228 | None |
| 37 | `DOC-a040ac19abb88fec` | True | 0.409700 | 33.0 | 2206 | 141 | None |
| 38 | `DOC-91f89b9c0d285ac7` | True | 0.666700 | 33.3 | 6902 | 126 | None |
| 39 | `DOC-204c3c7c0ba021cd` | True | 0.474600 | 33.2 | 2226 | 133 | None |
| 40 | `DOC-2819b889b134ea01` | True | 0.750000 | 33.6 | 5344 | 149 | None |
| 41 | `DOC-e478fa89043a29e3` | True | 0.820500 | 34.0 | 2910 | 151 | None |
| 42 | `DOC-2338d194d5250def` | True | 0.486700 | 15.0 | 5258 | 126 | None |
| 43 | `DOC-ffb48271e0a5e812` | True | 0.666700 | 20.0 | 5344 | 144 | None |
| 44 | `DOC-78f2456f571403a9` | True | 0.153100 | 17.1 | 2345 | 144 | None |
| 45 | `DOC-37152a33cfb70d37` | True | 0.410300 | 20.4 | 2902 | 161 | None |
| 46 | `DOC-00193d0c070747e6` | True | 0.714300 | 20.7 | 3225 | 173 | None |
| 47 | `DOC-866139125545b36a` | True | 0.773300 | 15.9 | 5397 | 161 | None |
| 48 | `DOC-842215e36884da89` | True | 0.246700 | 15.6 | 5226 | 161 | None |
| 49 | `DOC-f21f3dadebb121e3` | True | 0.784300 | 20.8 | 3308 | 180 | None |
| 50 | `DOC-d0aebe650be3e512` | True | 0.497600 | 13.3 | 2405 | 163 | None |
