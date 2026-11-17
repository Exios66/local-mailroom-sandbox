# Autoresearch study `mailroom-v1`

- mode: paid (OpenRouter)
- champion: `ar-mailroom-v1-r00-baseline`, mean utility -0.101
- rounds run: 2; kept 0, reverted 2, errors 0, aborted by the API cap 0, skipped 0
- noise floor (keep rule): 0.1479
- estimated spend: 2.7031 of 15 USD (round cap 1 USD)
- consecutive reverts: 2 (stop at 3)
- holdout: not run

Cost is an estimate from recorded tokens priced per model (`config/api_prices.yaml`), not the provider's bill.

## Ledger

| # | round | lever | decision | delta (CI) | utility | USD/doc | cost USD | USD per +0.01 | reasons |
|--:|--:|:---|:---|:---|--:|--:|--:|--:|:---|
| 1 | 0 | `baseline` | pending | - | - | - | 0.0000 | - | reserved 1 USD before the run started; the run's own row supersedes it |
| 2 | 0 | `baseline` | baseline | - | -0.101 | 0.01440 | 0.6789 | - | the champion's own run |
| 3 | - | `replicate` | pending | - | - | - | 0.0000 | - | reserved 1 USD before the run started; the run's own row supersedes it |
| 4 | - | `replicate` | replicate | -0.038 [-0.197, +0.099] | -0.140 | 0.01081 | 0.4746 | - | noise floor 0.1479: max(configured 0, /mean delta/ 0.0384, CI half-width 0.1479) between the two baseline runs |
| 5 | 1 | `merger-agreement-deepseek-v4.1-flash` | pending | - | - | - | 0.0000 | - | reserved 1 USD before the run started; the run's own row supersedes it |
| 6 | 1 | `merger-agreement-deepseek-v4.1-flash` | revert | +0.099 [-0.035, +0.231] | -0.003 | 0.01436 | 0.8103 | -0.0000 | gain is not established: CI low -0.035 <= 0.14792 (mean +0.099); class drop: contract -0.238 (limit -0.05) |
| 7 | 2 | `merger-prompt-maud-v2` | pending | - | - | - | 0.0000 | - | reserved 1 USD before the run started; the run's own row supersedes it |
| 8 | 2 | `merger-prompt-maud-v2` | revert | -0.008 [-0.176, +0.149] | -0.109 | 0.01456 | 0.7394 | - | gain is not established: CI low -0.176 <= 0.14792 (mean -0.008); class drop: contract -0.238, insurance_claim… |

## Noise floor (replicate baseline)

The baseline's identical spec was run twice on the same draw (25 documents). Paired difference between the two runs: |mean| 0.0384, CI half-width 0.1479; configured floor 0.0000. Effective floor 0.1479: a lever is kept only when its paired CI low is above it. One repeat of the champion cost 0.2702 USD (the measured cost of a round).

## Kept levers

None yet.

## Champion cost split

- per-document cost by role (USD, whole run): {'oversight': 0.152867, 'worker': 0.207218}
- oversight cost share (oversight / worker): 0.74

## Champion weakness table

# Weakness table: ar-mailroom-v1-r00-baseline

25 documents, mean utility -0.101. Lost utility is `1 - utility` per document, charged to one node (rules: `autoresearch/diagnose.py`).

| class | node | lost | docs | share | actionable | causes |
|:---|:---|---:|---:|---:|:---|:---|
| merger_agreement | merger_agreement_specialist | 8.00 | 4 | 39% | yes | extraction:maud_wrong x4 |
| contract | contracts_specialist | 4.06 | 3 | 20% | yes | extraction:cuad_missed x2, extraction:partial x1 |
| contract | judge | 2.50 | 2 | 12% | yes | judge:partial_exhausted x2 |
| correspondence | correspondence_specialist | 2.00 | 1 | 10% | yes | extraction:wrong_value x1 |
| correspondence | judge | 1.25 | 1 | 6% | yes | judge:partial_exhausted x1 |
| insurance_claim | judge | 1.25 | 1 | 6% | yes | judge:judge_rejected x1 |
| merger_agreement | judge | 1.25 | 1 | 6% | yes | judge:judge_rejected x1 |
| insurance_claim | insurance_claims_specialist | 0.22 | 4 | 1% | yes | extraction:partial x4 |

## By node

| node | lost |
|:---|---:|
| merger_agreement_specialist | 8.00 |
| judge | 6.25 |
| contracts_specialist | 4.06 |
| correspondence_specialist | 2.00 |
| insurance_claims_specialist | 0.22 |

Unscorable archives (no loss charged, no gold): corporate_record 4, correspondence 3

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
| `dataset.strata.buckets` | [{'doc_class': 'contract', 'count': 5}, {'doc_class': 'corporate_record', 'coun… | [{'doc_class': 'contract', 'count': 18}, {'doc_class': 'corporate_record', 'cou… |
| `job.api_cost_cap_usd` | 1 | 2 |
| `job.max_wall_seconds` | 3600 | 7200 |
| `reviewer.backend` | <unset> | decisions |
| `reviewer.classes.contract` | <unset> | 0.78 |
| `reviewer.classes.corporate_record` | <unset> | 0.96 |
| `reviewer.classes.correspondence` | <unset> | 0.64 |
| `reviewer.classes.insurance_claim` | <unset> | 0.7 |
| `reviewer.classes.merger_agreement` | <unset> | 0.99 |
| `reviewer.model` | <unset> | openai/gpt-6-luna-decisions |
| `reviewer.questions` | <unset> | reviewer_decisions_v2 |
| `run_id` | ar-mailroom-v1-base | production-slice-0100 |
| `trace.tags` | ['sandbox', 'pipeline', 'openrouter', 'qwen3.7-flash', 'chat-reviewer', 'autore… | ['sandbox', 'pipeline', 'openrouter', 'qwen3.7-flash', 'decision-reviewer', 'pr… |

### Inherited unchanged (42 settings)

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
