# Autoresearch study `mailroom-v2`

- mode: paid (OpenRouter)
- champion: `ar-mailroom-v2-r00-baseline`, mean utility -0.274
- rounds run: 7; kept 0, reverted 6, errors 1, aborted by the API cap 0, skipped 4
- noise floor (keep rule): 0.0837
- estimated spend: 5.7837 of 15 USD (round cap 3 USD)
- consecutive reverts: 7 (stop at 7)
- holdout: not run

Cost is an estimate from recorded tokens priced per model (`config/api_prices.yaml`), not the provider's bill.

## Ledger

| # | round | lever | decision | delta (CI) | utility | USD/doc | cost USD | USD per +0.01 | reasons |
|--:|--:|:---|:---|:---|--:|--:|--:|--:|:---|
| 1 | 0 | `baseline` | pending | - | - | - | 0.0000 | - | reserved 3 USD before the run started; the run's own row supersedes it |
| 2 | 0 | `baseline` | baseline | - | -0.274 | 0.00903 | 1.2432 | - | the champion's own run |
| 3 | - | `replicate` | pending | - | - | - | 0.0000 | - | reserved 3 USD before the run started; the run's own row supersedes it |
| 4 | - | `replicate` | replicate | -0.027 [-0.113, +0.055] | -0.301 | 0.00928 | 1.2804 | - | noise floor 0.0837: max(configured 0, /mean delta/ 0.0271, CI half-width 0.0837) between the two baseline runs |
| 5 | 1 | `merger-agreement-deepseek-v4.1-flash` | pending | - | - | - | 0.0000 | - | reserved 3 USD before the run started; the run's own row supersedes it |
| 6 | 1 | `merger-agreement-deepseek-v4.1-flash` | revert | +0.056 [-0.038, +0.151] | -0.218 | 0.00826 | 1.4029 | -0.0001 | gain is not established: CI low -0.038 <= 0.083667 (mean +0.056); class drop: corporate_record -0.267 (limit … |
| 7 | 2 | `merger-prompt-maud-v2` | pending | - | - | - | 0.0000 | - | reserved 3 USD before the run started; the run's own row supersedes it |
| 8 | 2 | `merger-prompt-maud-v2` | revert | +0.030 [-0.038, +0.097] | -0.244 | 0.00623 | 0.8787 | -0.0009 | gain is not established: CI low -0.038 <= 0.083667 (mean +0.030) |
| 9 | 3 | `merger-agreement-window-400k` | pending | - | - | - | 0.0000 | - | reserved 3 USD before the run started; the run's own row supersedes it |
| 10 | 3 | `merger-agreement-window-400k` | revert | +0.067 [-0.004, +0.143] | -0.206 | 0.00415 | 0.5340 | -0.0007 | gain is not established: CI low -0.004 <= 0.083667 (mean +0.067) |
| 11 | - | `judge-all-merger-agreement` | skipped | - | - | - | 0.0000 | - | over_round_cap: runtime bound 3.449 USD > round cap 3 USD (per-agent estimate 3.449 USD) |
| 12 | - | `key_baseline` | warning | - | - | - | 0.0000 | - | key_start.json has no key identity (it predates it): the current key is adopted as its owner. If this is not … |
| 13 | 4 | `insurance-claims-deepseek-v4.1-flash` | pending | - | - | - | 0.0000 | - | reserved 3 USD before the run started; the run's own row supersedes it |
| 14 | 4 | `insurance-claims-deepseek-v4.1-flash` | revert | -0.108 [-0.238, +0.018] | -0.382 | 0.00195 | 0.2776 | - | gain is not established: CI low -0.238 <= 0.083667 (mean -0.108); class drop: corporate_record -0.283 (limit … |
| 15 | 5 | `ins-prompt-v5` | pending | - | - | - | 0.0000 | - | reserved 3 USD before the run started; the run's own row supersedes it |
| 16 | 5 | `ins-prompt-v5` | revert | +0.121 [+0.010, +0.230] | -0.153 | 0.00093 | 0.1584 | -0.0007 | gain is not established: CI low +0.010 <= 0.083667 (mean +0.121); class drop: contract -0.172 (limit -0.050),… |
| 17 | 6 | `ins-prompt-v4` | pending | - | - | - | 0.0000 | - | reserved 3 USD before the run started; the run's own row supersedes it |
| 18 | 6 | `ins-prompt-v4` | revert | +0.034 [-0.083, +0.144] | -0.240 | 0.00007 | 0.0086 | -0.0027 | gain is not established: CI low -0.083 <= 0.083667 (mean +0.034); class drop: corporate_record -0.417 (limit … |
| 19 | - | `judge-all-contract` | skipped | - | - | - | 0.0000 | - | over_round_cap: runtime bound 3.449 USD > round cap 3 USD (per-agent estimate 3.449 USD) |
| 20 | - | `judge-rejudge-retry` | skipped | - | - | - | 0.0000 | - | over_round_cap: runtime bound 3.449 USD > round cap 3 USD (per-agent estimate 3.449 USD) |
| 21 | - | `judge-max-passes-2` | skipped | - | - | - | 0.0000 | - | over_round_cap: runtime bound 3.449 USD > round cap 3 USD (per-agent estimate 3.449 USD) |
| 22 | 7 | `extraction-gate-v1.3.0` | pending | - | - | - | 0.0000 | - | reserved 3 USD before the run started; the run's own row supersedes it |
| 23 | 7 | `extraction-gate-v1.3.0` | error | - | - | - | 0.0000 | - | `sandbox run start` exited 1: 39/75 ok=39 errors=0 running [progress] 40/75 ok=40 errors=0 running [progress]… |

## Noise floor (replicate baseline)

The baseline's identical spec was run twice on the same draw (75 documents). Paired difference between the two runs: |mean| 0.0271, CI half-width 0.0837; configured floor 0.0000. Effective floor 0.0837: a quality lever is kept only when its paired CI low is above it. A `goal: cost` lever (a derived placement) is kept instead when its CI low is above -0.02 (not worse) and it saves enough cost. Both kinds must also pass the per-class drop and wrong-archive guards. One repeat of the champion cost 0.6962 USD (the measured cost of a round).

## Warnings

- key_start.json has no key identity (it predates it): the current key is adopted as its owner. If this is not the study's original key, move the file aside

## Kept levers

None yet.

## Champion cost split

- cost by role (USD, summed over the whole run, not per document): {'oversight': 0.183208, 'reviewer': 0.000203, 'worker': 0.494217}
- oversight cost share (oversight / worker): 0.37

## Champion weakness table

# Weakness table: ar-mailroom-v2-r00-baseline

75 documents, mean utility -0.274. Lost utility is `1 - utility` per document, charged to one node (rules: `autoresearch/diagnose.py`).

| class | node | lost | docs | share | actionable | causes |
|:---|:---|---:|---:|---:|:---|:---|
| merger_agreement | merger_agreement_specialist | 28.00 | 14 | 37% | yes | extraction:maud_wrong x14 |
| insurance_claim | insurance_claims_specialist | 14.51 | 15 | 19% | yes | extraction:partial x8, extraction:missing_field x4, extraction:wrong_value x3 |
| contract | judge | 13.75 | 11 | 18% | yes | judge:partial_exhausted x10, judge:judge_rejected x1 |
| contract | contracts_specialist | 8.00 | 4 | 11% | yes | extraction:cuad_missed x3, extraction:cuad_false x1 |
| correspondence | correspondence_specialist | 8.00 | 4 | 11% | yes | extraction:wrong_value x4 |
| corporate_record | corporate_records_specialist | 2.00 | 1 | 3% | yes | extraction:wrong_value x1 |
| merger_agreement | reviewer | 1.25 | 1 | 2% | yes | classification:reviewer_unknown x1 |

## By node

| node | lost |
|:---|---:|
| merger_agreement_specialist | 28.00 |
| insurance_claims_specialist | 14.51 |
| judge | 13.75 |
| contracts_specialist | 8.00 |
| correspondence_specialist | 8.00 |
| corporate_records_specialist | 2.00 |
| reviewer | 1.25 |

Unscorable archives (no loss charged, no gold): corporate_record 9, correspondence 11

## Production parity

Compared with `config/runs/production/slice-0100.yaml` (the adopted production configuration).

### Pipeline and scoring sources

- vendored llm-mailroom: `f83e3987cf9842ebf1e3f8778e0bb6e1d869c135`
- vendored llm-dojo-scoring: `025400f3d703531c5e1a76093e4b803ccc6fb576`
- baseline run lock, pipeline: source `vendored`, commit `f83e3987cf9842ebf1e3f8778e0bb6e1d869c135`, tree sha256 `5fa7e5bd9b0913f0`
- baseline run lock, dojo: source `vendored`, commit `025400f3d703531c5e1a76093e4b803ccc6fb576`, tree sha256 `8cb105c1fbd87316`

### Differs from `config/runs/production/slice-0100.yaml` (the study's base spec)

| setting | study base | production |
|:---|:---|:---|
| `dataset.strata.buckets` | [{'doc_class': 'contract', 'count': 15}, {'doc_class': 'corporate_record', 'cou… | [{'doc_class': 'contract', 'count': 18}, {'doc_class': 'corporate_record', 'cou… |
| `job.api_cost_cap_usd` | 3.0 | 2 |
| `reviewer.backend` | <unset> | decisions |
| `reviewer.classes.contract` | <unset> | 0.78 |
| `reviewer.classes.corporate_record` | <unset> | 0.96 |
| `reviewer.classes.correspondence` | <unset> | 0.64 |
| `reviewer.classes.insurance_claim` | <unset> | 0.7 |
| `reviewer.classes.merger_agreement` | <unset> | 0.99 |
| `reviewer.model` | <unset> | openai/gpt-6-luna-decisions |
| `reviewer.questions` | <unset> | reviewer_decisions_v2 |
| `run_id` | ar-mailroom-v2-r00-baseline | production-slice-0100 |
| `trace.tags` | ['sandbox', 'pipeline', 'openrouter', 'qwen3.7-flash', 'chat-reviewer', 'autore… | ['sandbox', 'pipeline', 'openrouter', 'qwen3.7-flash', 'decision-reviewer', 'pr… |

### Inherited unchanged (43 settings)

- `agent_knobs.intake.max_input_chars` = 600000
- `agent_knobs.sorter.max_input_chars` = 600000
- `agent_routes.boss.model` = qwen/qwen3.7-flash
- `agent_routes.boss.provider` = openrouter
- `agent_routes.judge.model` = qwen/qwen3.7-flash
- `agent_routes.judge.provider` = openrouter
- `confidence.by_class.contract.high` = 0.95
- `confidence.by_class.corporate_record.high` = 0.95
- `confidence.by_class.merger_agreement.arbiter_retry_max` = 1
- `confidence.by_class.merger_agreement.judge_max_passes` = 2
- `dataset.config` = ground_truth
- `dataset.draw` = ranked
- `dataset.exclude_ids_file` = config/production/excluded-ids.txt
- `dataset.interim_labels` = True
- `dataset.provider` = huggingface
- `dataset.repo` = Lucius-Morningstar/mailroom-dataset
- `dataset.require_task_gt` = True
- `dataset.revision` = bc9eab280044befb51e19dda3071d290a8677f42
- `dataset.sample_seed` = 3302
- `dataset.split` = all
- `engine.kind` = openrouter
- `engine.modal` = None
- `engine.model` = qwen/qwen3.7-flash
- `job.blind_routing` = True
- `job.concurrency` = 10
- `job.cost_cap_usd` = 0.5
- `job.fail_fast` = False
- `job.max_retries` = 1
- `job.max_wall_seconds` = 7200
- `job.mock` = False
- `job.mode` = endpoint
- `profile` = openrouter
- `prompt.agents.corporate_records_specialist.file` = corporate_records_specialist_condensed_v1
- `prompt.agents.corporate_records_specialist.source` = local
- `prompt.agents.correspondence_specialist.file` = correspondence_specialist_condensed_v3
- `prompt.agents.correspondence_specialist.source` = local
- `prompt.agents.insurance_claims_specialist.file` = insurance_claims_specialist_condensed_v3
- `prompt.agents.insurance_claims_specialist.source` = local
- `prompt.default.source` = code-default
- `schema` = sandbox.run/v1
- `task` = pipeline
- `trace.environment` = pilot
- `trace.sink` = none

### Champion vs the study's base spec (what the kept levers changed)

| setting | champion | base |
|:---|:---|:---|
| (none) | | |
