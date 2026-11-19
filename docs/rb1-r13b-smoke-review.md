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
| 4 | The comparison declared B non-inferior at p=0.0005 from 20 agreeing documents | Silent wrong statistics | A bootstrap cannot see a loss it never observed. An exact floor now applies: one-sided Clopper-Pearson bounds on both discordant rates at alpha/2 each (Bonferroni), so sampling error in the gains counts as well as in the losses, with the p-value inverting that bound. The more conservative of the bootstrap and the exact result wins. The 20-doc smoke now reads "not shown" (lower95 -16.8 / -16.7 pts). The macro-F1 claim also needs every class to carry at least ln(0.05)/ln(1 - K x margin) documents (29 for 5 classes at 2 pts), because a small class can hide a drop worth more than the margin. Merger agreements are exempt (owner decision, 2026-11-19): they are the smallest class but the longest and densest documents, so their shortfall is reported and does not block the claim. With that, dev-look1 (merger_agreement 20, every other class 54 or more) and held-out (59 or more per class) both meet the rule. |
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
hold. dev-look1 is now runbook-v2's, on dataset v9.3 (plan Deviations log D1): 280 of its 300 documents are runbook-v1's,
and the dev-look1 configs pin `ff4ca546`.

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

## Smoke 20b result and the document-form floor (2026-11-19)

Controls: 4.0.0 got 5/7 (it parked both intact documents as `multiple_documents`); 4.0.1 got
7/7. Smoke 20b met bars 1-4 and 6: both ledgers matched their estimates exactly, 2 corrections
applied, class accuracy 20/20 on both arms. It **failed bar 5**: 4.0.1 parked 4 intact
documents whose forced answers were correct (DOC-be1e form exhibit with blank signature lines,
DOC-52f9 merger ending in its index, DOC-0a73 complete signed merger, DOC-b005 reply quoting the
invitation). It fixed 3 of 4.0.0's 5 false parks, kept 2 and added 2, although its wording
names every one of these cases.

Smoke 20c reran the Luna arm with the form answer's probabilities recorded (PR #356). The
forms were identical to 20b. The 4 false parks put 0.55-0.79 of the form probability on human
forms; the 16 documents passed sat at 0.01-0.47. That separation is in-sample, so no floor is
set from it. Instead a floor is fitted on the calibration split
([`scripts/rb1_form_floor.py`](../scripts/rb1_form_floor.py)):

1. `rb1-r13b-formcal-intact-decision-luna-v4.0.1`: 10 calibration documents per class, taken
   as complete (negatives).
2. `rb1-r13b-formcal-defects-decision-luna-v4.0.1`: fragments and bundles built from those same
   rows, form known by construction (positives).
3. `rb1_form_floor.py fit` tabulates, per candidate floor, the defects that would reach
   extraction and the intact documents parked. The floor is the highest one that lets no
   defect through; an intact document parked with high mass is read before any floor ships,
   since it may be a real defect. The floor then ships as question set 4.0.2. dev-look1 is a
   dev check of that calibration-fitted floor, not an out-of-sample measurement: 4.0.1's
   wording was shaped on dev-look1, so its dev-look1 figures stay in-sample. Scale up by raising the bucket counts under a new run id.

## Form calibration draw 1: no zero-leak floor, so question set 4.0.2 (2026-11-19)

Draw 1 ran 50 calibration documents (10 per class, $0.10) and 67 defect copies built from them
($0.10). No error, every document read whole (largest 109k tokens). Under 4.0.1 as run: 7
intact parked (5 on the form question) and 9 defects passed to extraction.

Reading the 9 passed defects showed 4 were built wrong (complete documents, see below), and a
seeded sample of 10 of the 58 parked defects found none built wrong. Those 4 are listed in
[`formcal-draw1-misbuilt.ids`](../config/splits/rb1-r13b/formcal-draw1-misbuilt.ids) and
excluded with `fit --misbuilt`, which gives the corrected column.

| Floor on human mass | Defects passed, as built (of 67) | Defects passed, corrected (of 63) | Intact parked (of 50) |
| --- | --- | --- | --- |
| 0.40 | 3 | 2 | 8 |
| 0.50 | 9 | 5 | 5 |
| 0.70 | 16 | 12 | 2 |
| 0.75 | 20 | 16 | 1 |

The human-form mass ranks well: AUROC 0.966 (corrected; a random defect has a higher mass
than a random intact document 96.6% of the time). What fails is the zero-leak requirement: no
floor from 0.40 to 0.95 parks every defect, so no floor ships. A floor of 0.50 matches 4.0.1's
chosen form on every row but one (`CAL-cut-691191d2`, mass exactly 0.50 after rounding), so a
floor near 0.5 changes nothing; a lower floor trades leaks for intact parks along the curve
above.

Uncertainty, corrected figures: 4.0.1 passes 5 of 63 defects (7.9%, one-sided 95% upper bound
16.0%) and parks 5 of 50 intact documents on the form question (10%, upper bound 19.9%).

Reading the 14 boundary documents:

- **4 defects were built wrong** (fixed in the builder): three cuts landed in an email's quoted
  history, leaving the newest message whole; one closing window was a whole signed addendum.
  Cuts now land in the newest message only, and a closing window that opens its own instrument
  is skipped.
- **5 defects were real misses**: a claim form cut off mid-word (mass 0.16), a Medicare
  notice that is only its header, a stock certificate cut mid-sentence, a contract followed by
  an unrelated newsletter after its filing footer, a short claim record followed by an SEC
  exhibit in `<DOCUMENT>` tags.
- **Intact parks**: a forwarded email thread (`multiple_documents`, 0.86), three long merger
  agreements (`fragment_or_excerpt`, 0.60-0.68; two end properly on signature pages or annex
  definitions, one lists annexes not attached) and a redacted (`[***]`) amendment. At least two
  of the five (the unattached annexes, the redaction) may be correct parks. 4.0.1's wording
  already calls the thread and the annex endings complete. No surface cue (omitted, continued,
  annex counts) separates the parked mergers from the 7 passed.

Caveats for every figure in this section:

- Draw 1 is in-sample for the builder fix and for 4.0.2, which were both written from it.
- Draws are class-balanced (10 per class; mergers 20% of the rows), so the rates are not
  production rates.
- "Intact" is assumed (the corpus has no form labels), and defects are labelled by
  construction; the readings above found errors in both directions.

[4.0.2](../config/decisions/reviewer_decisions_v4.0.2.yaml) changes `document_form` only: it
names the cut-off and header-only signs of a fragment and the unrelated-text-after-footer and
wrapper signs of a bundle, and says an email is judged by its newest message and a filed
agreement as filed.

### Draw 2 and the decision rule, fixed before it runs

Draw 2 is 100 calibration documents never used before (20 per class; draw 1 excluded by
[`formcal-draw2.exclude.ids`](../config/splits/rb1-r13b/formcal-draw2.exclude.ids)) and the
defects built from them with the fixed builder, each run under 4.0.1 and 4.0.2 (four runs,
about $0.85 at the caps' estimates). Doubling draw 1's size is for power: a one-sided sign test needs at least 5
discordant documents, all in one direction, to reach p < 0.05, and draw 1 had only 5 real leaks.

`rb1_form_floor.py compare` pairs the two question sets document by document and decides:

- For each side (defects passed, intact parked) it counts the documents 4.0.2 fixes and the
  ones it breaks (the discordant pairs) and runs a one-sided exact sign test on them.
- **Adopt 4.0.2** if the defect side improves by a net of at least 3 documents with p < 0.05,
  and the intact side loses at most 1 document net; or if the intact side improves by a net of
  at least 3 with p < 0.05 and no defect is lost net (a leak costs more than a park).
- **Reject** if either side is significantly worse (p < 0.05).
- Otherwise **inconclusive**: keep 4.0.1 and scale the draw before rewording again.

Mis-built defects found by reading draw 2 are listed in an ids file and passed with
`--misbuilt` before `compare` is read; the reading is done on both arms' passed defects alike.

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
- for decision models with a form question, `document_form_probabilities` and `document_form_human_mass`
- latency, tokens and cost

The truth needed is the corrected subclass labels (SHF-013) and the split membership. The
smoke runs had all of this. dev-look1 (300, about 60 per class) is enough to draw the first
per-class curves and test AUROC. Certification needs the calibration split.
