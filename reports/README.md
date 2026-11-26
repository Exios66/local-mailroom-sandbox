# Reports

Committed run reports, figures, serving exports and the reports hub. The offline experiment log
(`experiment_log.jsonl` / `.md`, written by `sandbox eval` / `sandbox matrix`) also lands here, but it
is gitignored runtime state, so a fresh checkout has none.

## Directory map

Ticket folders keep the spelling the code uses: `SAND-32`, `SAND-37` and `SAND-214` are hyphenated,
`SAND42` is not (`report_paths._FOLDER_ALIAS` maps `SAND-42` to it). Renaming one breaks the hub,
the card builders and their tests.

| Path | What it holds | Written by | Guard |
| --- | --- | --- | --- |
| `dashboard/` | Reports hub, floor viewer template, cross-repo exports | `dashboard/build_hub.py`, `export_hub_reports.py` | `build_hub.py --check` (CI) |
| `campaigns/` | Per-run trees for runbook campaigns (`rb1`) | `sandbox report build` | `sandbox report build --campaign rb1 --check` (CI) |
| `decisions/` | Decisions-model reviewer reports, figures and dashboard | `decisions/build_decisions_report.py` | `build_decisions_report.py --check` (CI) |
| `SAND-32/`, `serving/` | SAND-032 ladder and specialist reports, serving exports and figures | `scripts/sand032/report.py`, `sandbox metrics serving-record` | `scripts/sand032/rerender.py --check` (CI); the hub reads them |
| `SAND-37/` | SAND-037 specialist grid cards and figures | `sandbox run card`, `job/sand42_figures.py` | — |
| `SAND42/` | SAND-042 grid cards, master report and figures | `job/sand42_cards.py`, `scripts/sand42/` | — |
| `SAND-214/` | Window-run reports by date | `job/length_fix.py` | — |
| `YYYY-MM-DD/` | Runs that belong to no ticket, by date | `job/dated_reports.py` | `tests/test_dated_reports.py` |
| `autoresearch/` | Study ledgers and rounds | `autoresearch/loop.py` | — |
| `reviewer-calibration/` | Reviewer calibration and validation reports | `scripts/calibrate_reviewer.py` | — |
| `extraction-gate/` | Extraction-gate calibration | `scripts/extraction_gate.py` | — |
| `sorter-handoff/`, `specialist-condensed/`, `sorter-vs-decision-500/` | Prompt and arm comparisons | `scripts/compare_sorter_prompt.py`, `scripts/compare_specialist_prompt.py`; the sorter-vs-decision runs (`config/runs/sorter-vs-decision-*.yaml`) | — |
| `modernbert/` | ModernBERT classifier results (mailroom-ml) | — | the hub and cross-repo exports read them |
| `datasets/` | Dataset releases built here (v9.3 label-repaired) | the builder in each release folder | `tests/test_label_repaired_builder.py` |
| `a100/`, `gt-labeler/` | A100 manifest; EX10 CUAD labelling checkpoint | `scripts/build_a100_manifest.py`, `scripts/gt_label_ex10.py` | — |
| `archive/` | Superseded hand-written reports, read by the hub | hand-written | the hub reads them |
| `run-ledger.md` | Every paid run that passed the spend gate | `job/ledger.py` | `tests/conftest.py` |

## Reports hub

`dashboard/mailroom-reports.html` presents specialist, serving, hosted-API and ModernBERT results from this repo,
[eval-environment](https://github.com/LLM-Mailroom-Services/eval-environment) and
[mailroom-ml](https://github.com/LLM-Mailroom-Services/mailroom-ml). Every figure is read from a tracked file and
cross-checked; documented source defects are listed on its Data quality tab.

```bash
python reports/dashboard/build_hub.py sync      # re-pin eval-environment + mailroom-ml (sibling checkouts)
python reports/dashboard/build_hub.py           # rebuild the page
python reports/dashboard/build_hub.py --check   # fail if the page, data or snapshot is stale
```

| file | role |
| --- | --- |
| `dashboard/build_hub.py` | CLI: sync, build, check |
| `dashboard/hub_extract.py` | SAND-032, eval-environment and mailroom-ml extractors + cross-checks |
| `dashboard/legacy_runs.py` | 16–27 Sep specialist runs (pre-SAND-032) |
| `dashboard/external_snapshot.json` | pinned figures + provenance from the two sibling repos |
| `dashboard/hub.template.html` → `mailroom-reports.html` | page template → built page (`hub_data.json` is its data) |

Tabs: Overview · Specialists · Serving (Modal L4) · API models · **Modal vs API** (cost vs quality per
specialist task and for the sorter, both routes on one axis) · Classifier (ModernBERT) · ML diagnostics · Data quality.

## Campaign reports

Runbook-style campaigns file every run's records under `campaigns/<campaign>/` (today `rb1`,
the evaluation runbook v1). Each run iteration gets `logs/`, `traces/`, `outputs/`, `report/`,
`analysis/`, `figures/` and `docs/`, generated from the run logs by `sandbox report build` and,
for non-mock runs, at the end of the run. Every file name carries its full key
(`<run_id>-<iNN>.<name>.<ext>`), and `campaigns/rb1/index.jsonl` lists every run iteration.
Layout, naming grammar and the paths API: [campaigns/README.md](campaigns/README.md).

```bash
sandbox report build --run <run_id>          # one run's tree (all iterations)
sandbox report build --campaign rb1 --check  # fail if the committed indexes are stale
```

## Decision-reviewer reports

`decisions/` holds the reports, figures and dashboard for the Decisions-model reviewer experiments (SAND-085): cost
against a 1x Qwen call, effectiveness, the question-set lineage and the extraction gate. Start at
[`decisions/README.md`](decisions/README.md) or open `decisions/decisions-dashboard.html`.

```bash
python reports/decisions/build_decisions_report.py           # rebuild figures, CSVs, summary and dashboard
python reports/decisions/build_decisions_report.py --check   # fail if any output is stale
```

## Cross-repo reports (mailroom-issues)

`dashboard/export_hub_reports.py` turns the hub data into the cost comparison, the master status report and the
Modal + vLLM GPU economics report (`dashboard/gpu_report.py`) published in
`LLM-Mailroom-Services/mailroom-issues` under `reports/` (markdown + SVG only; that repo holds no code). The GPU
report reads the hub's `fleet` section: every `serving/SAND-32/sand032-*.serving.json` cross-checked against its run report.
`dashboard/report_audit.json` records the figure/link audit the master report cites.
`dashboard/breakeven.py` is the single Modal-vs-API break-even calculation (per document: warm-fleet and cold-batch
break-evens, the optimal measured deployment) that the cost comparison, the GPU report and the site all quote.

The same run also renders the reports as a static GitHub Pages site, `dashboard/pages_site.py` → `--site`
(default `<out>/../docs`, i.e. `mailroom-issues/docs/`): `index.html` plus `reports/*.html`, with every figure inlined as
SVG, no JavaScript and no external requests. mailroom-issues serves it by deploying from branch `main` `/docs`
(https://llm-mailroom-services.github.io/mailroom-issues/). `--check` covers the site too.

`dashboard/export_pngs.py` renders every figure to a 2× PNG under `mailroom-issues/reports/viz/` for slides; its
`MANIFEST.json` records each source SVG's SHA-256, so `--check` detects stale PNGs without a browser
(`CHROMIUM_PATH` selects a pre-installed Chromium when writing).

```bash
python reports/dashboard/export_hub_reports.py --out ../mailroom-issues/reports           # write reports + docs/ site
python reports/dashboard/export_pngs.py --reports ../mailroom-issues/reports               # write reports/viz/*.png
python reports/dashboard/export_hub_reports.py --out ../mailroom-issues/reports --check   # exit 1 if either is stale
```

## SAND-032 figures

`SAND-32/<class>/figures/*.svg` and `serving/figures/*.svg` are written by `scripts/sand032/report.py`
(needs the machine-local `data/runtime/` run artifacts). To apply a chart-kit (`scripts/sand032/viz.py`)
layout change to the committed figures without re-running GPU jobs:

```bash
python scripts/sand032/rerender.py           # re-lay every figure from the data embedded in it
python scripts/sand032/rerender.py --check   # exit 1 if any figure is stale
```

`rerender.py` refuses to write if a figure's data (every mark's hover title) would change.
