# Run report — `sand42-50-corporate-records-specialist-awq-2l4-c16`

Dated cell stem: `RUN-50-CORPORATE-AWQ-2L4-C16`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `sand42-50-corporate-records-specialist-awq-2l4-c16` |
| task / agent | `corporate_records_specialist` |
| prompt | `corporate_records_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **2×L4** |
| concurrency | **16** |
| n | **50** |
| profile | `modal-vllm` |
| spec_hash | `aca0ec6aaa37f5fc8934deb6587ff8b454e8963ee8cc7a4d1661556461c8e4ab` |
| dataset fingerprint | `76b083c7c46d` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **50 / 0 / 50** |
| **overall_extraction_score** | **0.498024** |
| schema_valid_rate | 0.980000 |
| error_count | 0 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 53.708 |
| gpu_seconds | 54.006 |
| estimated GPU cost | 0.024003 |
| **GPU $/doc** | **0.00048006** |
| latency p50 / max (s) | 11.186168 / 21.198734 |
| prompt / completion tokens | 197319 / 8278 |
| concurrency speedup (Σlat/wall) | 11.04 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-6790430ae2a6c724` | True | 0.184600 | 11.0 | 4477 | 143 | None |
| 2 | `DOC-a040ac19abb88fec` | True | 0.409700 | 11.0 | 2206 | 141 | None |
| 3 | `DOC-0a262afc80c73247` | True | 0.113600 | 11.0 | 3124 | 153 | None |
| 4 | `DOC-81ae205a3b0bf16f` | True | 0.248000 | 11.2 | 2515 | 158 | None |
| 5 | `DOC-12a6d4cd092cf66d` | True | 0.502600 | 11.2 | 7710 | 158 | None |
| 6 | `DOC-0f56fe8db6df01bd` | True | 0.063500 | 11.3 | 5368 | 161 | None |
| 7 | `DOC-020d77c0107d273d` | True | 0.472200 | 13.5 | 2302 | 203 | None |
| 8 | `DOC-c4c9c37a96291975` | True | 0.081300 | 16.1 | 2424 | 136 | None |
| 9 | `DOC-91f89b9c0d285ac7` | True | 0.666700 | 16.1 | 6902 | 129 | None |
| 10 | `DOC-9ca44c7926a47ede` | True | 0.502400 | 16.1 | 2292 | 140 | None |
| 11 | `DOC-fbcdd16e24f143ac` | True | 0.158200 | 16.5 | 2456 | 155 | None |
| 12 | `DOC-e545bbd5f5ea61b6` | True | 0.363600 | 16.6 | 2788 | 158 | None |
| 13 | `DOC-e077f1f7e80e1e04` | True | 0.162400 | 7.4 | 4043 | 153 | None |
| 14 | `DOC-f134b9491efc5c57` | True | 0.794900 | 7.3 | 2865 | 158 | None |
| 15 | `DOC-732b812b7d9d9653` | True | 0.888900 | 18.8 | 5572 | 165 | None |
| 16 | `DOC-01054efd0980066b` | True | 0.822200 | 19.1 | 5122 | 159 | None |
| 17 | `DOC-b3ad98e5530dfeaf` | True | 0.282000 | 9.4 | 2521 | 182 | None |
| 18 | `DOC-2819b889b134ea01` | True | 0.750000 | 20.9 | 5344 | 175 | None |
| 19 | `DOC-68d5a8753fcc3675` | True | 0.440500 | 21.2 | 5671 | 189 | None |
| 20 | `DOC-9376c6bfa6779d5e` | True | 0.482200 | 11.4 | 2200 | 150 | None |
| 21 | `DOC-fc9f56d999bd7566` | True | 0.666700 | 9.2 | 2509 | 184 | None |
| 22 | `DOC-2f19002c84083aa8` | True | 0.436300 | 11.5 | 5200 | 157 | None |
| 23 | `DOC-474a0002b4c03be1` | True | 0.820500 | 9.4 | 2938 | 150 | None |
| 24 | `DOC-d015968793450753` | True | 0.805600 | 10.2 | 5082 | 166 | None |
| 25 | `DOC-1e8e3ce47882ae71` | True | 0.148500 | 15.6 | 3063 | 200 | None |
| 26 | `DOC-b832b5eaa2b4848c` | True | 0.106800 | 8.4 | 2762 | 157 | None |
| 27 | `DOC-bfa92eb6c72569ee` | True | 0.451800 | 7.8 | 3771 | 160 | None |
| 28 | `DOC-37152a33cfb70d37` | True | 0.410300 | 7.3 | 2902 | 170 | None |
| 29 | `DOC-e478fa89043a29e3` | True | 0.820500 | 13.6 | 2910 | 151 | None |
| 30 | `DOC-0a8eb16fff7e67ca` | True | 0.692300 | 7.2 | 5246 | 150 | None |
| 31 | `DOC-41b53ea487b84955` | True | 0.750000 | 11.8 | 4617 | 233 | None |
| 32 | `DOC-a5fd7fe18b094f20` | True | 0.848500 | 13.8 | 5919 | 149 | None |
| 33 | `DOC-204c3c7c0ba021cd` | True | 0.474600 | 14.2 | 2226 | 152 | None |
| 34 | `DOC-9467462d9bb34f8e` | True | 0.541700 | 15.1 | 5345 | 161 | None |
| 35 | `DOC-4dc719baa790a79c` | True | 0.666700 | 18.5 | 2669 | 190 | None |
| 36 | `DOC-f21f3dadebb121e3` | True | 0.784300 | 9.2 | 3308 | 180 | None |
| 37 | `DOC-78f2456f571403a9` | True | 0.180900 | 8.3 | 2345 | 165 | None |
| 38 | `DOC-00193d0c070747e6` | True | 0.714300 | 14.5 | 3225 | 177 | None |
| 39 | `DOC-ffb48271e0a5e812` | True | 0.666700 | 12.8 | 5344 | 145 | None |
| 40 | `DOC-2338d194d5250def` | True | 0.486700 | 6.5 | 5258 | 128 | None |
| 41 | `DOC-d4dfbfe8049d41f9` | True | 0.490700 | 8.4 | 3856 | 179 | None |
| 42 | `DOC-842215e36884da89` | True | 0.246700 | 7.0 | 5226 | 164 | None |
| 43 | `DOC-e6906e59f9bd74ca` | True | 0.620000 | 10.3 | 2978 | 162 | None |
| 44 | `DOC-d0aebe650be3e512` | True | 0.497600 | 4.7 | 2405 | 163 | None |
| 45 | `DOC-a973ebf005e0e785` | True | 0.427800 | 15.7 | 6146 | 234 | None |
| 46 | `DOC-606242f2919653a4` | True | 0.233200 | 8.4 | 5253 | 159 | None |
| 47 | `DOC-866139125545b36a` | True | 0.773300 | 10.3 | 5397 | 180 | None |
| 48 | `DOC-dfe42f3747f299e6` | True | 0.750000 | 8.4 | 5870 | 164 | None |
| 49 | `DOC-80e90a37bb750a3c` | True | 0.165400 | 12.2 | 2776 | 213 | None |
| 50 | `DOC-27bbad54b6fd107e` | True | 0.833300 | 5.8 | 2871 | 169 | None |
