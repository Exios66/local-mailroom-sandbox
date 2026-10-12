# Run report — `sand42-50-corporate-records-specialist-awq-1l4-c8`

Dated cell stem: `RUN-50-CORPORATE-AWQ-1L4-C8`. Written automatically under the local-date specialist tree.

| | |
| --- | --- |
| run_id | `sand42-50-corporate-records-specialist-awq-1l4-c8` |
| task / agent | `corporate_records_specialist` |
| prompt | `corporate_records_specialist_v1` |
| engine | `Qwen/Qwen3-8B-AWQ` |
| GPU shape | **1×L4** |
| concurrency | **8** |
| n | **50** |
| profile | `modal-vllm` |
| spec_hash | `4640639b77be18b6b293e54690edaabb31ed4fe2709ff68e36bff59dd277e2ef` |
| dataset fingerprint | `76b083c7c46d` |

## Headline results

| metric | value |
| --- | --- |
| docs ok / failed / total | **50 / 0 / 50** |
| **overall_extraction_score** | **0.482250** |
| schema_valid_rate | 0.960000 |
| error_count | 0 |

## Serving / cost (see sibling `-SERVING.md`)

| metric | value |
| --- | --- |
| wall_seconds | 81.277 |
| gpu_seconds | 81.418 |
| estimated GPU cost | 0.018093 |
| **GPU $/doc** | **0.00036186** |
| latency p50 / max (s) | 10.791702 / 17.920535 |
| prompt / completion tokens | 197319 / 8154 |
| concurrency speedup (Σlat/wall) | 6.57 |

## Per-document scores

| # | doc id | ok | overall | latency s | prompt tok | compl tok | error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `DOC-6790430ae2a6c724` | True | 0.184600 | 10.8 | 4477 | 142 | None |
| 2 | `DOC-01054efd0980066b` | True | 0.822200 | 10.8 | 5122 | 158 | None |
| 3 | `DOC-e545bbd5f5ea61b6` | True | 0.363600 | 10.8 | 2788 | 155 | None |
| 4 | `DOC-fbcdd16e24f143ac` | True | 0.158200 | 10.8 | 2456 | 155 | None |
| 5 | `DOC-12a6d4cd092cf66d` | True | 0.502600 | 10.9 | 7710 | 158 | None |
| 6 | `DOC-9ca44c7926a47ede` | True | 0.502400 | 10.9 | 2292 | 167 | None |
| 7 | `DOC-81ae205a3b0bf16f` | True | 0.248000 | 10.9 | 2515 | 169 | None |
| 8 | `DOC-020d77c0107d273d` | True | 0.474600 | 17.9 | 2302 | 203 | None |
| 9 | `DOC-91f89b9c0d285ac7` | True | 0.666700 | 11.4 | 6902 | 128 | None |
| 10 | `DOC-c4c9c37a96291975` | True | 0.081300 | 11.5 | 2424 | 136 | None |
| 11 | `DOC-a040ac19abb88fec` | True | 0.409700 | 12.8 | 2206 | 141 | None |
| 12 | `DOC-0a262afc80c73247` | True | 0.113600 | 13.0 | 3124 | 153 | None |
| 13 | `DOC-2819b889b134ea01` | True | 0.750000 | 13.1 | 5344 | 151 | None |
| 14 | `DOC-0f56fe8db6df01bd` | True | 0.063500 | 13.2 | 5368 | 161 | None |
| 15 | `DOC-732b812b7d9d9653` | True | 0.888900 | 13.8 | 5572 | 156 | None |
| 16 | `DOC-68d5a8753fcc3675` | True | 0.440500 | 9.9 | 5671 | 178 | None |
| 17 | `DOC-e077f1f7e80e1e04` | True | 0.162400 | 8.2 | 4043 | 160 | None |
| 18 | `DOC-9376c6bfa6779d5e` | True | 0.482200 | 6.8 | 2200 | 139 | None |
| 19 | `DOC-f134b9491efc5c57` | True | 0.794900 | 7.2 | 2865 | 148 | None |
| 20 | `DOC-2f19002c84083aa8` | True | 0.436300 | 9.1 | 5200 | 162 | None |
| 21 | `DOC-b3ad98e5530dfeaf` | True | 0.282000 | 10.7 | 2521 | 190 | None |
| 22 | `DOC-1e8e3ce47882ae71` | True | 0.148500 | 12.2 | 3063 | 198 | None |
| 23 | `DOC-fc9f56d999bd7566` | True | 0.666700 | 11.6 | 2509 | 204 | None |
| 24 | `DOC-4dc719baa790a79c` | True | 0.666700 | 10.5 | 2669 | 163 | None |
| 25 | `DOC-e478fa89043a29e3` | True | 0.820500 | 10.2 | 2910 | 151 | None |
| 26 | `DOC-474a0002b4c03be1` | True | 0.820500 | 10.2 | 2938 | 152 | None |
| 27 | `DOC-d015968793450753` | True | 0.722200 | 11.0 | 5082 | 159 | None |
| 28 | `DOC-a5fd7fe18b094f20` | True | 0.848500 | 9.8 | 5919 | 145 | None |
| 29 | `DOC-204c3c7c0ba021cd` | True | 0.474600 | 7.1 | 2226 | 133 | None |
| 30 | `DOC-b832b5eaa2b4848c` | True | 0.106800 | 9.1 | 2762 | 157 | None |
| 31 | `DOC-9467462d9bb34f8e` | True | 0.541700 | 9.4 | 5345 | 162 | None |
| 32 | `DOC-41b53ea487b84955` | True | 0.750000 | 16.6 | 4617 | 239 | None |
| 33 | `DOC-bfa92eb6c72569ee` | True | 0.118400 | 10.8 | 3771 | 158 | None |
| 34 | `DOC-37152a33cfb70d37` | True | 0.410300 | 9.9 | 2902 | 161 | None |
| 35 | `DOC-00193d0c070747e6` | True | 0.714300 | 12.0 | 3225 | 181 | None |
| 36 | `DOC-ffb48271e0a5e812` | True | 0.666700 | 8.9 | 5344 | 144 | None |
| 37 | `DOC-0a8eb16fff7e67ca` | True | 0.692300 | 9.0 | 5246 | 150 | None |
| 38 | `DOC-a973ebf005e0e785` | True | 0.427800 | 14.5 | 6146 | 212 | None |
| 39 | `DOC-f21f3dadebb121e3` | True | 0.784300 | 13.2 | 3308 | 181 | None |
| 40 | `DOC-80e90a37bb750a3c` | True | 0.149500 | 11.8 | 2776 | 188 | None |
| 41 | `DOC-78f2456f571403a9` | True | 0.153100 | 10.1 | 2345 | 144 | None |
| 42 | `DOC-e6906e59f9bd74ca` | True | 0.620000 | 12.0 | 2978 | 160 | None |
| 43 | `DOC-2338d194d5250def` | True | 0.486700 | 10.5 | 5258 | 129 | None |
| 44 | `DOC-d4dfbfe8049d41f9` | True | 0.493400 | 12.5 | 3856 | 175 | None |
| 45 | `DOC-866139125545b36a` | True | 0.773300 | 11.6 | 5397 | 168 | None |
| 46 | `DOC-606242f2919653a4` | True | 0.233200 | 8.9 | 5253 | 156 | None |
| 47 | `DOC-842215e36884da89` | True | 0.246700 | 7.9 | 5226 | 162 | None |
| 48 | `DOC-d0aebe650be3e512` | True | 0.497600 | 6.4 | 2405 | 163 | None |
| 49 | `DOC-dfe42f3747f299e6` | True | 0.750000 | 6.7 | 5870 | 166 | None |
| 50 | `DOC-27bbad54b6fd107e` | True | 0.500000 | 5.1 | 2871 | 183 | None |
