# Run report — `rb1-r13b-controls-decision-luna-v4.0.1-i01`

| | |
| --- | --- |
| campaign / experiment | `rb1` / `rb1-r13b` |
| run_id / iteration | `rb1-r13b-controls-decision-luna-v4.0.1` / `i01` |
| status | **done** |
| task / model | `sorter_reviewer` / `openai/gpt-6-luna-decisions` |
| spec_hash | `99a29459097d33ff160d866fbab6c34708bef21fabd9c74e406581a3f119582f` |
| started → finished | 2026-11-19T11:10:02.712+00:00 → 2026-11-19T11:10:04.248+00:00 |
| documents ok / failed / total | 7 / 0 / 7 |
| dataset | `form-controls.jsonl` @ `bc9eab280044befb51e19dda3071d290a8677f42` (ground_truth/all) |
| source | [rb1-r13b-controls-decision-luna-v4.0.1-i01.report.json](rb1-r13b-controls-decision-luna-v4.0.1-i01.report.json) |

## Headline (run scorer, from the experiment log)

| metric | value |
| --- | --- |
| error_count | 0 |
| exact_match | 0.2857 |
| n | 7 |
| subclass_corrections_applied | 0 |
| subclass_match | 0.2857 |
| subclass_match_hub_truth | 0.2857 |
| subclass_scored | 7 |

## Subclass by truth class (SHF-013, reviewed corrections applied)

| class | n | correct | accuracy | Hub-truth accuracy |
| --- | --- | --- | --- | --- |
| contract | 1 | 0 | 0.0000 | 0.0000 |
| corporate_record | 1 | 0 | 0.0000 | 0.0000 |
| insurance_claim | 2 | 1 | 0.5000 | 0.5000 |
| merger_agreement | 3 | 1 | 0.3333 | 0.3333 |

## Figures

Each figure's data is in [`analysis/rb1-r13b-controls-decision-luna-v4.0.1-i01.figure-data.csv`](../analysis/rb1-r13b-controls-decision-luna-v4.0.1-i01.figure-data.csv)

![Stacked bars per group: documents archived correct, parked, misarchived, unscored](../figures/rb1-r13b-controls-decision-luna-v4.0.1-i01.routing.svg)
![Strip plot of chosen-class probability for right and wrong forced answers](../figures/rb1-r13b-controls-decision-luna-v4.0.1-i01.confidence.svg)
![Step line of error rate among archived documents against coverage, run routing marked](../figures/rb1-r13b-controls-decision-luna-v4.0.1-i01.risk-coverage.svg)
![Bar chart of how many documents each park rule fired on](../figures/rb1-r13b-controls-decision-luna-v4.0.1-i01.park-reasons.svg)
![Bar chart of subclass accuracy per truth class among archived documents](../figures/rb1-r13b-controls-decision-luna-v4.0.1-i01.subclass.svg)
![Scatter of latency against input tokens per document, log scales](../figures/rb1-r13b-controls-decision-luna-v4.0.1-i01.latency.svg)

## Cost and serving (serving renderer)

| metric | value |
| --- | --- |
| estimated_cost_usd | 0.011255 |
| cost_per_document | 0.001608 |
| cost_basis | token_price_estimate |
| wall_seconds | 15.076000 |
| prompt_tokens | 112550 |
| completion_tokens | — |

## Caveats

- Cost basis is `token_price_estimate` (from the serving renderer), not a provider invoice.
- docs/ config is the committed config today; the spec lock in logs/ is authoritative.
