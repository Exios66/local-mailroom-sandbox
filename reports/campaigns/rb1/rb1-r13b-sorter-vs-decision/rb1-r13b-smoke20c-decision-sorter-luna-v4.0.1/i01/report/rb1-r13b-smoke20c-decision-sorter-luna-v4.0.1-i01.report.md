# Run report — `rb1-r13b-smoke20c-decision-sorter-luna-v4.0.1-i01`

| | |
| --- | --- |
| campaign / experiment | `rb1` / `rb1-r13b` |
| run_id / iteration | `rb1-r13b-smoke20c-decision-sorter-luna-v4.0.1` / `i01` |
| status | **done** |
| task / model | `sorter_reviewer` / `openai/gpt-6-luna-decisions` |
| spec_hash | `8c595ad317476b8e2f2a7f1840a7733210483b72e62614c4b269e6c33b864b4c` |
| started → finished | 2026-11-19T11:20:32.471+00:00 → 2026-11-19T11:20:34.722+00:00 |
| documents ok / failed / total | 20 / 0 / 20 |
| dataset | `Lucius-Morningstar/mailroom-dataset` @ `bc9eab280044befb51e19dda3071d290a8677f42` (ground_truth/all) |
| source | [rb1-r13b-smoke20c-decision-sorter-luna-v4.0.1-i01.report.json](rb1-r13b-smoke20c-decision-sorter-luna-v4.0.1-i01.report.json) |

## Headline (run scorer, from the experiment log)

| metric | value |
| --- | --- |
| error_count | 0 |
| exact_match | 0.8000 |
| n | 20 |
| subclass_corrections_applied | 2 |
| subclass_match | 0.8000 |
| subclass_match_hub_truth | 0.7000 |
| subclass_scored | 20 |

## Subclass by truth class (SHF-013, reviewed corrections applied)

| class | n | correct | accuracy | Hub-truth accuracy |
| --- | --- | --- | --- | --- |
| contract | 4 | 3 | 0.7500 | 0.7500 |
| corporate_record | 4 | 4 | 1.0000 | 0.7500 |
| correspondence | 4 | 3 | 0.7500 | 0.7500 |
| insurance_claim | 4 | 4 | 1.0000 | 1.0000 |
| merger_agreement | 4 | 2 | 0.5000 | 0.2500 |

## Figures

Each figure's data is in [`analysis/rb1-r13b-smoke20c-decision-sorter-luna-v4.0.1-i01.figure-data.csv`](../analysis/rb1-r13b-smoke20c-decision-sorter-luna-v4.0.1-i01.figure-data.csv)

![Stacked bars per group: documents archived correct, parked, misarchived, unscored](../figures/rb1-r13b-smoke20c-decision-sorter-luna-v4.0.1-i01.routing.svg)
![Strip plot of chosen-class probability for right and wrong forced answers](../figures/rb1-r13b-smoke20c-decision-sorter-luna-v4.0.1-i01.confidence.svg)
![Strip plot of document-form probability on human forms per group, park line at 0.5](../figures/rb1-r13b-smoke20c-decision-sorter-luna-v4.0.1-i01.form-mass.svg)
![Bar chart of how many documents each park rule fired on](../figures/rb1-r13b-smoke20c-decision-sorter-luna-v4.0.1-i01.park-reasons.svg)
![Bar chart of subclass accuracy per truth class among archived documents](../figures/rb1-r13b-smoke20c-decision-sorter-luna-v4.0.1-i01.subclass.svg)
![Scatter of latency against input tokens per document, log scales](../figures/rb1-r13b-smoke20c-decision-sorter-luna-v4.0.1-i01.latency.svg)

## Cost and serving (serving renderer)

| metric | value |
| --- | --- |
| estimated_cost_usd | 0.045774 |
| cost_per_document | 0.002289 |
| cost_basis | token_price_estimate |
| wall_seconds | 19.085000 |
| prompt_tokens | 457738 |
| completion_tokens | — |

## Caveats

- Cost basis is `token_price_estimate` (from the serving renderer), not a provider invoice.
- docs/ config is the committed config today; the spec lock in logs/ is authoritative.
