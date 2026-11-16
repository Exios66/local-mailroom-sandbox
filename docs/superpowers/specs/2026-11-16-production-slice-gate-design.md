# Production slice gate: fewer reviews and no wrong archives (design)

Date: 2026-11-16. Tracking: #300. Builds on #303 (blind routing, interim labels, paired report).

## Intent

The aim is a Mailroom pipeline that a professional user (an insurer's claims unit, a legal
department) can run with **as little human review as possible** while archiving only
extractions of professional grade. Every decision must be auditable from the traces and the
hash archive. The pipeline should extract as many documents as possible completely under the
Dojo extraction schemas, and its mechanisms (judge, arbiter, retries, decision reviewer) must
behave as designed.

Production here means CLI-launched runs (`sandbox run start`) over fixed slices of the Hugging
Face mailroom dataset, growing towards the whole dataset. Documents land in the hash archive
(`data/archive/SANDBOX-<run>-DOC-<hash>/<class>/`). A run executes in one of three places:
1. locally, with every model call going to OpenRouter;
2. on Modal, with the `sandbox-job` worker running the job and vLLM on Modal serving the models;
3. on a VM, from the Docker image.

Why measure this way: E3 (45 held-out documents, r3 settings) sent only 2 documents to review.
However, 14 of its 43 archived documents score below 0.7 on their labelled fields, and none was
flagged:

| Class | Archived | Archived below 0.7 |
|---|---|---|
| merger | 5 | 5 |
| correspondence | 9 | 6 |
| contract | 9 | 2 |
| corporate | 10 | 1 |
| insurance | 10 | 0 |

A wrong archive is worse than a review, because nobody looks at it. "Fewer reviews" and
"fewer wrong archives" are therefore one objective.

## Goals

- **G1 — Slice gate.** Each slice run reports, per class and overall:
  - **review rate:** the share of documents ending at `stage: review`;
  - **wrong-archive rate:** the share of archived documents scoring below the quality bar on
    real labelled fields;
  - **archived-correct rate:** the share archived at or above the bar, the yield;
  - a pass or fail against the bars below.
- **G2 — Cause buckets.** Every review and every wrong archive gets exactly one primary cause,
  read from the run artifacts (`items.jsonl`, `nodes.jsonl`, traces). Each gets a link back to
  its archive directory and trace, so the report is the audit trail.
- **G3 — Fix loop.** Fix the known mechanism bugs, then the largest cause bucket. Re-run the
  same slice to confirm each fix, and only then step to the next slice size.
- **G4 — Thresholds from evidence.** Per-class routing thresholds come from slice evidence
  (review rate against wrong-archive rate), not intuition. A threshold change is accepted only
  if it holds the wrong-archive bar.
- **G5 — Execution parity, then a self-hosted ladder.** There are two stages:
  - **Job-host parity:** a slice that passes locally reproduces on the Modal `sandbox-job`
    worker. The worker still calls the same models through OpenRouter, uses the same pinned
    snapshots, and its provenance must match. A run on a VM from the Docker image uses the
    same CLI and the same checks.
  - **Self-hosted ladder:** this starts once the OpenRouter slices pass. Modal vLLM serves an
    open model, and the pipeline has its own slice ladder under the same gate and bars.

## Bars (agreed)

| Bar | Value | Scope |
|---|---|---|
| Quality bar for a correct archive | ≥ 0.90 on labelled fields | per document |
| Wrong-archive rate | ≤ 2% of archived | per slice, gated classes |
| Review rate | ≤ 5% of documents | per slice, gated classes |
| Crashes | 0 run errors, 0 `judge_error` | per slice |

- **Gated classes:** contract, corporate_record, correspondence and insurance_claim.
  **merger_agreement is excluded** until its MAUD extraction works. It is still run and
  reported, but it never fails a slice.
- **Labelled fields:** the scored Dojo fields that have a real label. That means the Hub label
  plus `dataset.interim_labels`, without the templated fields (`TEMPLATED_FIELDS`, corporate and
  correspondence `keywords` / `subject_matter`).
- **Score:** the 0.90 bar applies to the Dojo per-document aggregate
  (`_score_pipeline_extraction` → `overall_extraction_score`, partial credit included). It is
  computed on the row without the templated fields, exactly as `job/pair_report.py` scores it.
- **Too few labels:** a document whose labelled fields fall below a minimum (suggested 2) is
  "unscorable".
  - It stays in the review-rate denominator: if it was reviewed it counts as a review; if it
    was archived it does not.
  - It is left out of the wrong-archive rate.
  - The report lists it with its count.

**Pass rule:** a slice passes when, over the gated classes pooled together:
- the wrong-archive rate is at or under 2%;
- the review rate is at or under 5%;
- there are no crashes.

These are point estimates. The gate also prints each rate's Wilson 95% upper bound and the
per-class rates. At slice 100 a single wrong archive in one class is about 5%, so per-class
rates are diagnostic only. They must also meet the bar from slice 500 on. Among the
configurations that pass, the one with the lowest review rate is adopted. *(My call after the
builder check: per-class point bars at about 20 archived documents would mean zero errors and
would be dominated by noise.)*

## Non-goals

- Tuning MAUD merger extraction (excluded from the bars for now).
- Retuning the reviewer cutoffs (issue #208), unless a cause bucket points there.
- Judging every extraction, the E1 contract chunk setting and `judge_rejudge_retry`: these
  failed their ladder steps and stay off.
- A new label-free document intake service. Production in this phase is the CLI run.

## Anti-goals

These would make the work a failure even if every gate passed:
- **Any label in routing.** Every production slice runs with `job.blind_routing: true`; a slice
  that routes on labels is invalid.
- **Lowering review by archiving wrong extractions:** a review rate that falls while the
  wrong-archive rate rises is a regression.
- **Hidden decisions:** any archive or review without a trace and an archive path that explain
  it.
- **Patching `vendor/`:** pipeline-logic fixes land in llm-mailroom first and arrive through a
  vendor refresh (`/vendor-sync`).
- **Unprompted paid runs:** every slice is launched by a human through the spend gate.

## Constraints

- Vendored pins: llm-mailroom `abb1ccf` and Dojo `13adc8e`. Another agent is triaging the open
  llm-mailroom issues (#207, #253, #254, #255). Fixes there are coordinated, not duplicated.
- Dataset: `Lucius-Morningstar/mailroom-dataset`, `ground_truth`, pinned revision `bc9eab28`.
- **Slice nesting:** each slice must be a superset of the previous one (same seed, nested
  draws), so results compare document by document. If the current stratified sampler does not
  nest when its counts grow, the slice configs must make it nest.
- **Held out:** the slices exclude every document already used for tuning: r2/r3, E1, E2, E3,
  and the sorter and specialist prompt-tuning draws where those are recorded. Fixes and
  thresholds are tuned on slice N, so a step-up's verdict is read on the **new** documents only
  (slice N+1 minus slice N). The gate reports that as its own section, alongside the
  whole-slice numbers. *(My call after the builder check.)*
- **Decision reviewer:** unchanged from r3 (`openai/gpt-6-luna-decisions` with the v2 cutoffs).
  "Qwen3.7 Flash on every agent" means every pipeline agent, not the reviewer.
- **Audit trail:**
  - the local span mirror (`data/traces/<run_id>.spans.jsonl.gz`, `trace.sink: none`, no
    Docker);
  - `nodes.jsonl`;
  - the hash archive.

  The gate fails a slice when any document lacks spans or a node log, or when an archived
  document lacks its archive directory. Langfuse is optional. *(My call after the builder
  check.)*
- **Spend:** every slice config sets `job.max_wall_seconds` and `job.api_cost_cap_usd`, and a
  GPU run also sets `job.cost_cap_usd`. The cap is scaled from the measured cost per document
  (E3: about 76k prompt tokens per document; mergers about 410k).
- Local checks run network-free. Full-suite and coverage checks run in hosted CI, and the
  coverage floor stays at 84.

## Approaches

| | Approach | Trade-off | Decision |
|---|---|---|---|
| A | **Measure, then fix the biggest failure, slice by slice.** Build the gate report and cause buckets, run a calibration slice, fix the mechanism bugs then the largest bucket, confirm on the same slice, then step up. | Slower to the first change; every change is proven before it scales. | **Chosen.** |
| B | Tighten thresholds first, in config only. | Fast, but E2 showed that confidence (≥ 0.95 on nearly everything) and the judge do not separate good from bad, so review would rise without catching wrong archives. | Rejected: works against the goal. |
| C | Build a field-level verification gate now: schema enums, required fields, value present in the source, before archiving. | The strongest and most auditable catch, but an upstream feature built before the failures are measured. | Deferred. It is expected to be an early fix once the buckets justify it. |

## Design

### 1. Slice configs

- **Slice ladder:** `config/runs/production/slice-0100.yaml`, `-0250`, `-0500`, `-full`. Each
  carries the r3 settings:
  - blind routing;
  - interim labels;
  - the adopted condensed specialist prompts;
  - context fit;
  - the r3 confidence block;
  - Qwen3.7 Flash on every agent, through OpenRouter.
- **Class mix:** proportional to the dataset at the pin. Mergers stay in the mix.
- **Locks:** every slice is locked and hashed as usual. The configs differ only in `limit`,
  their strata counts, `run_id` and the caps.
- **Modal job-host twins:** each slice has a twin that changes only `job.mode: modal`. The
  engine stays OpenRouter. It is used for the G5 job-host parity check.

### 2. Gate report (`sandbox run gate`)

- **Command:** `sandbox run gate --run-id <id> [--bars config/production/bars.yaml] [--json]`.
  It runs offline and makes no LLM calls.
- **Inputs:** the run directory, scored the same way as `job/pair_report.py`, and the bars
  file.
- **Outputs:**
  - per class: n, review rate, wrong-archive rate, archived-correct rate, unscorable count and
    tokens per document;
  - the overall gated rates, and a PASS or FAIL with the bar that failed;
  - the cause-bucket table (section 3);
  - per-document rows with: class, stage, score, cause, archive path and trace id.
- **Written artifacts:** `gate.json` and `gate.md` in the run directory. A run-ledger line
  links them.
- **Two-run form:** with a second run id, the gate also prints the paired difference on shared
  documents, reusing `pair_report`.

### 3. Cause buckets

Each document that is reviewed or wrongly archived gets one primary cause, by fixed precedence:

1. **mechanism faults:** `judge_error` and other exceptions, transient-provider exhaustion,
   run errors;
2. **classification:** a sorter/reviewer disagreement, the reviewer answering `unknown` or an
   ineligible label, a wrong class archived;
3. **judge or arbiter:** `judge_partial` with retries exhausted, arbiter escalation;
4. **extraction:** per wrong archive, the field-level miss type (field missing, wrong value,
   out-of-enum value, date-format mismatch), read from the Dojo field scores;
5. **label suspect:** a heuristic or templated label that disagrees with an extraction found
   verbatim in the source text. These are reported separately and filed against the dataset,
   not the pipeline.

Each bucket lists its document ids, archive paths and trace ids, so a reviewer can audit the
cause from the artifacts.

### 4. Fix loop

1. **Slice 100, baseline:** run, gate and bucket.
2. **Known mechanism bugs first:**
   - the contract second judge pass `TypeError` (seen in both r3 and E3; `graph/build_graph.py`
     judge node). Reproduce it offline from the archived state, find the root cause, then fix
     it upstream if it is vendored or here if it is sandbox wiring;
   - the decision reviewer answering `unknown` on correspondence email: look at the reviewer
     prompt and label space on the sandbox side first.
3. **Largest bucket:** take the bucket with the most gated documents. The fix lands where it
   belongs:
   - prompts, thresholds and wiring here;
   - pipeline logic in llm-mailroom, for example best-attempt (#254), bounded retry priming
     (#253), or approach C's verification gate;
   - labels in llm-dojo-scoring or the interim overlay.
4. **Confirm on the same slice:** a fix is accepted when the paired gate shows the
   wrong-archive rate is not worse and the review rate or yield is better.
5. **Step up:** when slice N passes, run the next slice. A failure at the larger slice returns
   to step 3 on that slice.

### 5. Threshold calibration (G4)

From a slice's per-document confidences and scores, the gate prints for each gated class the
review rate and wrong-archive rate a candidate `high` / `judge_band_high` would have produced,
by replaying routing offline where the decision is threshold-only. A threshold change goes into
the slice configs only through the same confirm step (step 4).

### 6. Execution parity (G5)

**Stage 1 — job-host parity.** After a local slice passes, its Modal job-host twin runs, still
calling OpenRouter. The two are accepted as equivalent only if:
- the `dependency_sources` provenance matches (same vendored commits and tree hashes);
- the per-class gate rates fall within the paired CI.

The job worker bundles the vendored snapshots selected for the run. A VM run uses the Docker
image with the same CLI and the same checks.

**Stage 2 — self-hosted ladder.** This starts after the OpenRouter slices pass. The current
Modal server (`deploy/modal_vllm.py`) serves Qwen3.5-9B with a 16k–32k context window on an L4.
A merger needs about 410k tokens and long contracts need about 90k, so context fit chunks them
heavily and the pipeline behaves differently. Stage 2 therefore:
- runs its own slice ladder, starting at slice 100, with the same gate, bars and cause
  buckets;
- keeps the decision reviewer on its API model, unless the reviewer is moved explicitly;
- sets `job.cost_cap_usd` (GPU) on every config;
- runs on the `jjburleson` Modal account's free credits.

Choosing the model and GPU size (a larger context or a bigger model) is part of stage 2. It is
decided from the stage-2 slice-100 buckets, not in advance.

## Decided by the user

- The objective: minimise human review while archiving only professional-grade extractions,
  fully auditable through traces and the hash archive.
- The bars: 0.90 quality, at most 2% wrong archives and at most 5% review per slice. Mergers
  are kept out of the bars for now.
- Approach A.
- CLI-launched slices of the Hugging Face dataset, growing towards the whole dataset; local
  OpenRouter, Modal, or a VM with the Docker image.
- Modal in two stages: first as the job host still calling OpenRouter (parity), then as a
  self-hosted vLLM model server with its own slice ladder, once the OpenRouter slices pass.

## Left to the builder

- The minimum labelled-field count for "scorable" (suggested 2).
- The cause precedence details and the exact miss-type taxonomy, from Dojo's field scorers.
- Whether `sandbox run gate` extends `sandbox run routing`'s audit module or stands alone.
- How the slice configs guarantee nesting.
- Cost caps per slice, from measured cost per document with about 2× headroom.
