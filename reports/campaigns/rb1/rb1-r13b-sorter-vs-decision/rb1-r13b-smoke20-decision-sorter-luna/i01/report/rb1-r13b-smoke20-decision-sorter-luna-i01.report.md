# Run report — `rb1-r13b-smoke20-decision-sorter-luna-i01`

| | |
| --- | --- |
| campaign / experiment | `rb1` / `rb1-r13b` |
| run_id / iteration | `rb1-r13b-smoke20-decision-sorter-luna` / `i01` |
| status | **done** |
| task / model | `sorter_reviewer` / `openai/gpt-6-luna-decisions` |
| spec_hash | `4513c54a798af2d1a823a77971f6a6952e92140644d46b410d375437b9fd9ddf` |
| started → finished | 2026-11-19T07:43:40.978+00:00 → 2026-11-19T07:43:47.877+00:00 |
| documents ok / failed / total | 20 / 0 / 20 |
| dataset | `Lucius-Morningstar/mailroom-dataset` @ `bc9eab280044befb51e19dda3071d290a8677f42` (ground_truth/all) |
| source | [rb1-r13b-smoke20-decision-sorter-luna-i01.report.json](rb1-r13b-smoke20-decision-sorter-luna-i01.report.json) |

## Headline (run scorer, from the experiment log)

| metric | value |
| --- | --- |
| error_count | 0 |
| exact_match | 0.7500 |
| n | 20 |

## Figures

Each figure's data is in [`analysis/rb1-r13b-smoke20-decision-sorter-luna-i01.figure-data.csv`](../analysis/rb1-r13b-smoke20-decision-sorter-luna-i01.figure-data.csv)

![Stacked bars per group: documents archived correct, parked, misarchived, unscored](../figures/rb1-r13b-smoke20-decision-sorter-luna-i01.routing.svg)
![Strip plot of chosen-class probability for right and wrong forced answers](../figures/rb1-r13b-smoke20-decision-sorter-luna-i01.confidence.svg)
![Bar chart of how many documents each park rule fired on](../figures/rb1-r13b-smoke20-decision-sorter-luna-i01.park-reasons.svg)
![Scatter of latency against input tokens per document, log scales](../figures/rb1-r13b-smoke20-decision-sorter-luna-i01.latency.svg)

## Cost and serving (serving renderer)

| metric | value |
| --- | --- |
| estimated_cost_usd | 0.045470 |
| cost_per_document | 0.002273 |
| cost_basis | token_price_estimate |
| wall_seconds | 107.583000 |
| prompt_tokens | 454698 |
| completion_tokens | — |

## Caveats

- Cost basis is `token_price_estimate` (from the serving renderer), not a provider invoice.
- docs/ config is the committed config today; the spec lock in logs/ is authoritative.
