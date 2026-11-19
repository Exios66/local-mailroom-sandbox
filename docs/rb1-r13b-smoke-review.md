# rb1 R13b smoke review: LLM sorter vs decision model (H5)

Campaign `rb1` (SAND-108). Row R13b (hypothesis H5) asks whether a Decisions-API model can
replace the LLM sorter. This page reviews the first controlled smoke and sets the bar for the
checkpoint smoke (20b). Passing 20b unlocks dev-look1 (300 documents), then dev (600/900).

## Runs reviewed (2026-11-19)

| Arm | Run | Model | Prompt / question set |
| --- | --- | --- | --- |
| A, LLM sorter | `rb1-r13b-smoke20-llm-sorter-qwen3.7-flash` | `qwen/qwen3.7-flash` (Alibaba) | `sorter_condensed_v5` |
| B, decision sorter | `rb1-r13b-smoke20-decision-sorter-luna` | `openai/gpt-6-luna-decisions-20261006` | `reviewer_decisions_v4.0.0` |

Both arms ran on the same 20 dev-look1 documents: 4 per class, `sample_seed` 20261118, corpus
revision `bc9eab28`. Both used concurrency 8 and read every document whole in one request.

Arm B's task is named `sorter_reviewer`. That is the harness's task name for the decisions
backend, not its role. Question set 4.0.0 has no handoff, so the model never sees a sorter
answer: it classifies class and subclass from the document alone, as THE sorter. The
reviewer role, a cheap verification layer over the LLM agents, is question set 3.1.0, which
reads the sorter's handoff. That is a separate study.

## What worked

- **Mechanics:** 20/20 items on both arms, 0 errors, exactly 1 call per document.
  - Every call was served by the pinned model and provider: 20 Alibaba calls for A, 20 OpenAI
    calls on the dated snapshot for B.
  - Report folders were written under
    `reports/campaigns/rb1/rb1-r13b-sorter-vs-decision/<run>/i01/`.
- **Class:** 20/20 on both arms.
- **Subclass, after the comparison's canonical matching:** A 17/20, B 18/20.
  - `Distributor` / `distributor` and `Affiliate_Agreements` / `affiliate` already count as
    matches.

## Runtime: the decision model's biggest advantage

| | LLM sorter | Decision model | Ratio |
| --- | --- | --- | --- |
| Active wall time, first call to last answer | 21.4 s | 3.4 s | 6.3x |
| Run wall time, start to done event | 24.3 s | 6.9 s | 3.5x |
| Sum of per-document latency | 103.7 s | 18.9 s | 5.5x |
| Median document latency | 2.84 s | 0.79 s | 3.6x |
| Merger agreement mean latency (~75k tokens) | 13.7 s | 1.6 s | 8.3x |
| Throughput at concurrency 8 | 56 docs/min | 350 docs/min | 6.3x |

The gap grows with document length, because the decision model writes no output tokens. At
these rates a 100k-document backlog at concurrency 8 takes about 30 h with the LLM sorter and
about 4.8 h with the decision model. Each provider's rate limits must be checked before
projecting beyond concurrency 8.

The comparison now reports this per arm and per pair (see Fixes).

## Errors and misaligned behaviour, with the fix for each

| # | Finding | Effect | Fix |
| --- | --- | --- | --- |
| 1 | Runs with `trace.sink: none` ended with `Transient error ... localhost:3000/api/public/otel/v1/traces` and `Failed to export spans batch` | Noise, and a sink-agnostic run contacting a trace backend | The vendored pipeline built a real Langfuse client whenever `LANGFUSE_SECRET_KEY` was set. `sink: none` now also sets `LANGFUSE_TRACING_ENABLED=false` for the run. Only the local spans mirror (`data/traces/<run>.spans.jsonl.gz`) is written. A chosen sink still exports. |
| 2 | Run report cost for qwen3.7-flash: $0.0145; actual $0.0402 | Silent wrong cost (2.8x low) | qwen is priced in tiers: $0.10/M from 32k prompt tokens. The report priced run totals at the flat rate. It now prices each item at its own tier. |
| 3 | Served ledger had provider and model but no cost | Spend could not be checked against the provider | Ledger rows carry the provider's `usage.cost` and token counts when reported. The run digest sums `reported_cost_usd`. |
| 4 | The comparison declared B non-inferior at p=0.0005 from 20 agreeing documents | Silent wrong statistics | A bootstrap cannot see a loss it never observed. An exact Clopper-Pearson floor on discordant losses now applies, and the more conservative result wins. The 20-doc smoke now reads "not shown" (lower95 -13.9 / -8.9 pts). |
| 5 | The run report scored only doc_type, with no subclass metric | Subclass errors invisible per run | SHF-013 adds subclass scoring with canonical matching to the run report, dual-reported against `raw_dojo`. |
| 6 | 3 subclass "misses" looked like label errors: charter amendment labelled `board_resolution`; $9.50 all-cash merger labelled `other`; internal email about "demand letter recipients" labelled `demand` | Arms penalised for correct answers | SHF-013 applies 2 reviewed corrections at scoring time (`data/labels/review/subclass_corrections.jsonl`) and keeps raw figures under `raw_dojo` / `hub_truth`. The third was **rejected** on review: the corpus labels correspondence by marker precedence (first marker anywhere in the text wins), and all 37 correspondence documents that contain "demand letter" are labelled `demand` or `attorney_demand`, none `email`. The Hub `demand` stands, so qwen's `email` is a real miss and luna's `demand` is right. |
| 7 | 4.0.0 parked 5/20 documents, and all 5 were false: FNOL claim files with their invoice; a merger with its amendment; a merger ending in its index; an unsigned form exhibit | 25% needless human routing | Question set 4.0.1 narrows `document_form` only. Positive controls (`scripts/rb1_build_form_controls.py`) must show real fragments and bundles still park. |
| 8 | The LLM sorter routed 6/20 to a person, all correct | 30% needless human routing on arm A | qwen states 0.95 on every contract, below the 0.98 `high` band, so its verbal confidence carries no ranking information. The comparison should report routing for both arms (open). This is a calibration/threshold question for R03-style sorter work, not a code bug. |

### Two smaller observations

- A parked decision document scores `match 0` in the run's own report (SHF-007). The comparison
  scores its forced answer and reports parking separately. Both views are intended; read the
  comparison for H5.
- The strata block in the digest prints B minus A per stratum. At n=20 every stratum is tiny,
  so ignore it until dev-look1.

## Checkpoint: smoke 20b and the form controls

Order of launch:

1. Controls on 4.0.0, then on 4.0.1.
2. `rb1-r13b-smoke20b-llm-sorter-qwen3.7-flash`.
3. `rb1-r13b-smoke20b-decision-sorter-luna-v4.0.1`.

Launch one at a time. Each config's header has the exact commands. The total is about $0.20.

Proceed to dev-look1 (300 documents per arm, about $0.6 + $0.7 at the smoke's per-document rates) only when all of the following
hold:

1. **Mechanics:** 20/20 items, 1 call per document, every ledger row verified, and no trace
   exporter errors on the console.
2. **Cost:** each arm's provider-reported ledger total is within 5% of the run report's estimate.
3. **Scoring:** the run reports show a subclass metric, and SHF-013 applied the 2 `correct` corrections (the DOC-f4ce proposal is `rejected` and not applied).
   The comparison shows runtime and routing for both arms.
4. **Controls:** 4.0.1 gets 7/7 on `--check-run`: all 5 fragments and bundles parked, and both
   intact documents passed.
5. **False parks:** 4.0.1 parks at most 1 of the 20 smoke documents with a correct forced
   answer. This number is in-sample: the fix was written from these documents.
6. **Class:** class accuracy is 20/20 on both arms. This is a regression check, not evidence.

The non-inferiority tests are expected to read "not shown" at n=20. They are not part of this
bar; dev-look1 is where H5 starts to be measured.

## Confidence thresholds: what the smoke showed and how they will be calibrated

Both arms' needless human routing (findings 7 and 8) is a threshold problem. Every routing
threshold in the pipeline today is hand-set. They come from three places:

- `pipeline.config` confidence bands: sorter `high` 0.95 to 0.98 per class, `low`, and
  `judge_band_high`.
- The decision sets' `abstain` rules: `margin` 0.10, `unknown_max` 0.34 and
  `subclass_not_this_class_max` 0.50, all marked provisional in 4.0.0.
- The per-class `subclass_gate`.

None of them has been fitted to evidence. The runbook already reserves the calibration step:

- R50 runs the final sorter over the 1,000-document calibration split.
- R51 fits the calibrators and certifies per-class gates. That is H3: at most 2% wrong
  auto-routes, as a one-sided 95% Clopper-Pearson upper bound, per class.

The smoke adds three requirements before that work can succeed.

### 1. A threshold needs a confidence signal that ranks

A cutoff only helps if right and wrong answers differ in confidence.

- qwen's stated confidence is close to a constant: 0.95 on every contract and 1.0 on most
  other documents. No cutoff on it can separate right from wrong, so the 0.98 contract band
  simply routes every contract to a person.
- The decision model returns a full probability vector per question. Its class probabilities
  ranged 0.87 to 1.00 on the smoke, so it can rank.
- Neither arm made a class error in 20 documents. Their separating power (AUROC of confidence
  against correctness) is therefore still unmeasured.

Before any threshold is fitted, each run is checked for whether its signal ranks:

- per-class AUROC with a CI
- the share of answers at the top value (saturation, already in `calibrate_reviewer.py`)

A stage whose signal does not rank gets a different signal instead of a threshold. Candidates:

- the decision model's probability as the gate on the LLM sorter's answer (the 3.1.0 reviewer
  role)
- agreement between the LLM sorter and the decision model
- token log-probabilities where the provider returns them

### 2. Thresholds per class and per stage, each with its own evidence

| Stage | Threshold | Signal | Fitted on | Tool |
| --- | --- | --- | --- | --- |
| Sorter (LLM) | per-class `high` / `low` band | stated confidence, or a replacement signal (see 1) | R50, calibration split | to build: generic risk-coverage fit (below) |
| Sorter (decision model) | per-class auto-route cutoff; `abstain.margin`, `unknown_max`, `subclass_not_this_class_max` | class and subclass probability vectors | a decision-sorter pass over calibration | to build (4.0.0's `open_for_4.1.0`) |
| Decision reviewer (3.1.0 role) | per-class cutoff on gated confidence | reviewer probability | calibration | `scripts/calibrate_reviewer.py` (exists: per-class cutoff, 5-fold cross-fit, routing at cutoffs) |
| Subclass gate | per-class subclass cutoff, or park | subclass probability | calibration | to build |
| Judge / arbiter | `judge_band_high`, retry limits | judge score | pipeline runs (R4x/R72) | later; needs pipeline runs |
| Specialists | per-field acceptance, if any | field confidence | R4x | later; field-level, not class-level |

### 3. The method, for every threshold

1. **Fit only on the calibration split.** dev-look1, look2 and dev runs are for exploring
   curves. Any number from them is in-sample and labelled as such. Held-out stays sealed for
   the confirmatory check.
2. **Per class, compute the risk-coverage curve:** for each candidate cutoff, the share of
   documents auto-routed (coverage) and the wrong-route rate among them (risk).
3. **Choose the lowest cutoff that meets the target.** Its 95% one-sided Clopper-Pearson upper
   bound on wrong routes must be at most the target (2%, H3). This needs at least 149
   error-free accepts per class. Classes the calibration split cannot fund report their
   certified bound instead (contract, corporate_record, merger_agreement; decision 6).
4. **Estimate out-of-sample behaviour with 5-fold cross-fitting**, as `calibrate_reviewer.py`
   does. Each fold is scored at a cutoff fitted on the other four.
5. **Report the operating point,** not just the cutoff. At the chosen cutoff, report:
   - automation rate
   - human-review load per 1,000 documents
   - wrong routes per 1,000
   - model cost per 1,000
   - throughput

   Compare the LLM sorter, the decision sorter and the LLM + decision-reviewer cascade at the
   same risk target. This answers which design moves the most documents through unattended at
   2% risk, at what cost and speed.

### What each upcoming run must record (already true; keep it true)

Every item records:

- predicted class and subclass
- the stage's confidence and, for decision models, the whole probability vectors
- the forced answer and the park reason
- latency, tokens and cost

The truth needed is the corrected subclass labels (SHF-013) and the split membership. The
smoke runs had all of this. dev-look1 (300, about 60 per class) is enough to draw the first
per-class curves and test AUROC. Certification needs the calibration split.
