# Figure catalog

Each experiment asks a few fixed questions. Each question has one figure, already built unless
marked *to build*. File names follow `<stem>.<figure>.svg`.

## Per-run figures (any sorter or decision-model run)

Built by `decision_figures.build` and written with each run's report tree
(`sandbox report build --run <run id>`).

| Figure | Question | Form | Notes |
| --- | --- | --- | --- |
| `routing` | Where did each document go? | Stacked horizontal bars per group (class, or defect recipe on calibration runs) | Status colours; counts inside segments; n at the bar end |
| `confidence` | Does class probability rank right answers above wrong ones? | Dot strip, right vs wrong, passed slate / parked amber | AUROC in the subtitle; under 5 errors the title says too few to judge |
| `risk-coverage` | What error rate does a probability floor buy at each coverage? | Step line, run's routing as a black point | The threshold-calibration view; only when there is at least one error |
| `form-mass` | Does document-form probability separate defects from intact documents? | Dot strip per group with the 0.5 park line | AUROC defects vs intact on calibration runs |
| `park-reasons` | Which rule parked documents? | Horizontal bars, humanized rule names | One document can fire several rules: say so |
| `subclass` | How accurate is the subclass, per class, among archived documents? | Horizontal bars, percent axis, Wilson 95% whiskers, k/n labels | Small n shows as wide whiskers, not as a confident bar |
| `latency` | How does latency grow with document size? | Log-log scatter, worst document labelled | Median in the title; p95, throughput and cost per 1,000 in the subtitle |

## Sorter vs decision model (H5)

Built by `comparison_figures.build` from `sorter_arms.compare`; written by
`scripts/compare_sorter_arms.py --figures DIR` or `--write`.

| Figure | Question | Form |
| --- | --- | --- |
| `runtime` | How long does each arm take for the same documents? | Bars of total wall-clock run time (active time, first request to last answer, when the comparison is a subset of a run), labelled with documents/min and hours per 100k; title gives the speed-up range |
| `latency` | How long does one document take? | Dot strip per arm on a log axis, median bar and label |
| `quality` | Is the decision model non-inferior? | Forest plot: candidate minus reference, 95% paired bootstrap, dashed red margins |
| `routing` | How many documents does each arm send to a person, and how many does it auto-route wrongly? | Stacked bars, status colours |
| `cost-quality` | What does each arm cost for its accuracy, at this sample's length mix? | Scatter of cost per 1,000 documents against subclass-unit accuracy, direct labels, cost basis in the subtitle; billed totals when every arm has them, else list price × tokens for all; a cost direction in the title only on billed totals with n ≥ 1,000 |
| `pricing` | What does each model charge, by prompt size? | Step line of list input price per 1M tokens against prompt tokens (log), from `config/api_prices.yaml` with its checked date; the compared documents' prompt sizes as tick rows |

Run time is only comparable at the same concurrency on the same documents; the figure says when
concurrency differs. Cost is only comparable on the same basis and at scale: the subtitle names any arm priced from
`config/api_prices.yaml` rather than billed, and no figure claims a cheaper arm before a clean
comparison of at least 1,000 billed, paired documents. Refresh the sheet with
`scripts/refresh_api_prices.py --check` before quoting a price.

## Form-floor calibration (question set A vs B)

`decision_figures.paired_svg(stem, compare_result, base, cand)`: two panels, defects passed and
intact parked, base grey and candidate blue, the decision (adopt, reject, inconclusive) in the
title. *To wire*: `scripts/rb1_form_floor.py compare --figure`.

## Incremental scaling of the decision-model sample (*to build*)

Question: are the estimates stable as n grows? Form: one line per measure (park rate, misarchive
rate, subclass accuracy) against cumulative n, with a Wilson band, one panel per measure (never
two scales on one axis). Colour: the system colour; bands at 20% opacity of it.

## Per-class, per-stage thresholds (*to build*)

Question: which floor per class keeps misarchives under the target at the most coverage? Form:
small multiples of the per-class risk-coverage step line, shared axes, the chosen floor marked.

## Adding a figure

1. Name the question and the decision in the table above (add a row).
2. Implement it in the module that owns the data (`decision_figures` for a run,
   `comparison_figures` for arms), with `fs.Fig`, `fs.heading`, `fs.axis_labels` and the colour
   roles.
3. Compute the title from the data (see `text-rules.md`), add it to the report order
   (`_FIGURE_ORDER`, `_FIGURE_ALT` in `report_campaigns.py`) if it is a per-run figure.
4. Test: fixture build, computed title, `lint_svg == []`, determinism.
