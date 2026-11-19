---
title: "Mailroom sorter and extraction evaluation runbook — research plan"
type: plan
created: 2026-11-18
updated: 2026-11-18
status: draft  # becomes pre-registered once hypotheses H1-H4 and their falsification criteria are signed off
author: mixed
design: "Mailroom Sorter & Extraction Evaluation Design (Claude doc, tabs: design, Statistical review, EXPERIMENT CHECKLIST, Prompt iteration experiments, Decision model cycles)"
runbook: "experiment_runbook.csv (R00-R90, G0-G8)"
discussion: "https://github.com/Exios66/local-mailroom-sandbox/discussions/343"
---

# Mailroom sorter and extraction evaluation runbook — research plan

> Pre-registration contract for the runbook. Phase 0 (R00-R03, G0) has two parts:
> offline preparation that runs in this sandbox today (split, leak audit, statistics,
> schema registry, provider pins), and live work that needs human initials at the spend
> gate (the R01 smoke and the R03 v0 passes; findings 2 and 13). G0 cannot close on the
> offline part alone. Phases 1-9 also need initials. Nothing here launches paid work.

**Research question.** Can error-driven prompt iteration on a cheap model, transferred
to the production models and gated by certified calibration, raise sorter and
specialist accuracy and cut human review on the 3,302-document Mailroom corpus without
breaching a 2% wrong-auto-route bound?

**Method.** Freeze a four-way split (dev 900 / calibration 1,000 / held-out 1,000 /
rotation pool 402). Measure noise floors, iterate prompts on Qwen3.7 Flash with
sequential looks (300 / 600 / 900) and an exact-McNemar keep rule, transfer finished
versions to DeepSeek V4.1 Flash and GLM 5.3 FlashX Legal, certify gates with one-sided
Clopper-Pearson bounds on calibration, then run one sealed, Holm-adjusted confirmatory
pass on held-out.

## Hypotheses (pre-registered on sign-off)

| ID | Hypothesis | Primary metric | Falsified when |
| --- | --- | --- | --- |
| H1 | The final sorter beats v0 on the production model | class macro-F1, paired | Held-out macro-F1 gain < +3 pts or Holm-adjusted paired macro-F1 swap-permutation p ≥ 0.05 (`experiment_stats.paired_macro_f1`), computed on the 305 never-tuned held-out docs (primary). Accuracy and its exact McNemar are reported as a secondary result; McNemar tests paired correctness, not macro-F1 |
| H2 | Final specialists beat v0 on field F1 without more hallucination | per-doc field F1 (permutation test) | Gain < target (+3 or +4 pts by lineage) or hallucination not −30% relative, Holm-adjusted |
| H3 | A global auto-route gate holds at 2% wrong routes | 95% one-sided Clopper-Pearson upper bound | Bound ≥ 2% on calibration, or realized held-out error rate's bound ≥ 2% |
| H4 | The pipeline reduces human review versus production v0 | review-rate difference, 95% CI | CI includes 0 or the reduction is under 2 pts |

Stop criteria: per lineage — target met, maximum versions, or 5 rounds with nothing
kept. Held-out is unsealed once (R70-R72); nothing is re-run after unsealing.

## Runbook audit (evidence from this checkout, 2026-11-18)

Arithmetic checks that hold: R13 (6 × 300 = 1,800), R15 (900 + 1,200 = 2,100), R20
(4,500 + 2,700 + 2,700 + 900 = 10,800; ~$24 at the design's per-1,000 prices), R32
(5,400; ~$21), R50 (2,500-6,000; $9-22), split sizes (900 + 1,000 + 1,000 + 402 = 3,302).

| # | Row | Finding | Effect | Proposed resolution |
| --- | --- | --- | --- | --- |
| 1 | R70, R73 | Sorter prompts v1-v5 were tuned on the HF `train` split (2,979 docs; `config/production/excluded-ids.txt` header). Only 309 corpus docs are never-tuned (test split minus the tuning list). R73's reason ("no never-tuned docs remain") is not exact. | A 1,000-doc held-out is ~70% in-sample for the sorter lineage, so R70 overstates generalization. | A leak component is ranked by its most-exposed member, so held-out holds no tuning-list document and nothing linked to one (audit gate). It seats the 305 never-tuned docs not linked to a tuning-list doc, then 695 untuned train docs. The other 4 never-tuned docs share a component with tuning-list docs and sit in dev. Make H1's primary test the 305-doc subset (detectable gain ≈ 5 pts at 80% power), with the full 1,000 as secondary. |
| 2 | R03, G0 | The gold audit needs v0-vs-gold disagreements, but v0 first runs on dev in R20 (Phase 2). | G0 cannot close with only offline work. | Add a v0 sorter pass on dev to Phase 0 (900 Qwen3.7 Flash calls, ≈ $0.33, needs initials), or move R03 to just after R20. Audit dev and pool docs only, never held-out. |
| 3 | R02 | "field scorer @ e90ac8b9" names a gold-label commit, not a scorer. The scorer is the vendored Dojo pin (`_VENDOR_PINS`). Gold labels are unchanged since e90ac8b9 (HEAD adds only `data/labels/review/*`). | Ambiguous provenance. | Record both: labels at e90ac8b9 and the Dojo vendor pin. |
| 4 | R12, R40-R42 | No `contracts_specialist_condensed_*` exists (PI-C says "from v3"), corporate-record condensed has only v1 (PI-R says "from v2"), and there are no `decision-*-condensed` v0.4.0 question sets (`config/decisions/` has reviewer v1-v4, extraction_gate v1.0-1.3). | Those lineages have no starting version. | Name the actual starting stems before R12/R40, or create v0 stems as a logged deviation. |
| 5 | R40, R41 | "7 specialist lineages" vs 5 specialists; PI-M (merger) has 0 iteration versions. | Calls/cost overstated, or two lineages are missing from the design. | Correct to 5 lineages with 4 iterated, or name the other 2. |
| 6 | R14 | The listed grid gives 3,600 calls (Qwen 6 configs + temperature-0 run 3× = 8 runs × 300; DeepSeek and GLM 2 configs × 300 each), not 4,200. | Budget ambiguity. | State the runs per model explicitly. |
| 7 | R15 | The pool has 52 docs over 4k tokens (29 ≤16k, 8 ≤32k, 15 >32k). A 4K/8K cap only changes those. | The input-cap sweep is underpowered where it matters. | Score R15 on the >4k docs, adding dev long docs, since a cap is a serving choice rather than prompt tuning. |
| 8 | R51, G5 | Dev and held-out quotas (20 per unit) leave calibration with 75 contracts and 24 mergers. Certifying 2% at 95% needs ≥149 zero-error accepts. | Per-class gates for contract and merger are infeasible. Only the global gate (and correspondence or insurance) can certify. | Accepted by the design ("per class where supported"). Record it as expected. |
| 9 | R00 | The ±5-pt `source_corpus` / `annotation_method` rule conflicts with oversampling small classes (raw gaps 5-8.5 pts). | The rule cannot hold on raw mixes. | Gate within class on dev and held-out (max gap 3.0 pts); report raw and calibration gaps as information. |
| 10 | R00 | Only 23 docs carry `matter_id` / `group_id`. | Thread leakage is not covered by those fields alone. | The leak audit also links correspondence by normalized subject (reply/forward prefixes stripped) and identical normalized text: 24 components, largest 6, none crossing sets. `message_id` / `in_reply_to` / `related_document_ids` are linked when present, but never fire on this corpus (unique message ids, no replies or related ids recorded), so subject is the only thread signal. |
| 11 | All | Insurance claims (1,100) are 100% `synthetic`. The design's "637 correspondence labels are DeepSeek zero-shot" cannot be verified from the Hub (`annotation_model` is empty). DeepSeek is also a transfer target. | Possible label-model bias toward DeepSeek on correspondence; insurance results may not transfer to live traffic. | Do correspondence first in R03 (already planned) and report insurance separately in R80. |
| 12 | R01 | "all 10 + 4" models is undefined. `typesafe/jev-1.14` is not in `config/decision_models.yaml` (1.13 is). GLM is priced and profiled under the alias `z-ai/glm-5.3-flashx-legal`, while the design pins `-20261102`. | Smoke test scope and pins are unclear. | List the 14 models, run `scripts/refresh_decision_models.py`, and set the GLM canonical slug in `config/provider_pins.yaml` (done) and the price sheet. |
| 13 | R01 | Nothing pinned OpenRouter providers or recorded the served provider. | The R01 gate could not be checked. | Added `mailroom_sandbox.provider_pins` (below). The LangChain contract and merger agents are not covered yet. |
| 14 | R30 | 4-6 candidates per round are screened without multiplicity correction. | Dev "keeps" are optimistic. | Acceptable: the sealed held-out with Holm is the confirmatory family. Say so in R80. |
| 15 | R12, R40-R42 | The Dojo extraction registry freezes field statuses from the Hub v9 lineage: 23 class-level fields that now carry repaired truth (interim and near-gold overlays) still read `pending_annotation`; merger `intent` / `subject_matter` / `keywords` and indenture `filing_number` are labeled but marked `not_applicable`. Some output fields have no truth anywhere: all 30 corporate entity-extension fields, 11 merger fields, contract `merger_consideration` / `maud_clauses`, insurance `claim_checklist`. Others are constant (correspondence `demand_amount` always null, insurance `claim_type`, contract `party_roles` 90% `other`). | Iteration rounds and prompt tokens spent on fields nothing can score, or on a constant, measure nothing. | `sandbox schemas build` grades every (class, subclass) field from the truth a run scores, with a verdict: `iterate` (≥ 20 labeled dev docs), `thin`, `constant`, `fixed`, `no_truth`, `not_applicable`. It fails on truth the model cannot emit, a label outside its closed vocabulary, or a `record_type` that contradicts the subclass (0 today). Iterate only on `iterate` fields; state `constant` rules in the prompt. Runs scored on repaired labels set `interim_labels: true` and `near_gold_labels: true` (`sandbox splits show` prints them). |
| 16 | R40-R42 | The specialist output-schema descriptions the model reads are looser than the labeling guide for the repaired fields (`party_roles` has no role vocabulary, `recipient` / `urgency` / `demand_amount` have no convention), and the contracts prompt names 2 of the 9 repaired contract fields. | Scores against repaired labels partly measure the description gap, not the prompt. | `job.schema_guide: true` sets the guide's conventions as the descriptions of 20 fields (contract 9, corporate 4, correspondence 7). Corporate condensed v2 (Certificate of Designation, rights instruments, effective-date fallback, indenture governing law, execution-block signatories) and correspondence condensed v4 (recipient, demand, urgency rules) are lineage candidates. A/B each against its frontrunner on dev with the overlays and `schema_guide` on before adoption. |
| 17 | R03 | `data/labels/gold/decisions.jsonl` is not built into the gold catalogs (the label pass files are not in this checkout), and two owner decisions in `data/labels/VALIDATION.md` are open: interim-over-reviewed-gold precedence and 52 Hub correspondence intents judged wrong. | The registry's counts reflect the overlays as committed; gold changes after adjudication will move them. | Owner step before R03 closes. Rebuild with `sandbox schemas build` after any label change; `--check` fails on a stale registry. |

## What this change adds (Phase 0 pathways)

| Runbook row | Command / module | Status |
| --- | --- | --- |
| R00 split, families, leak audit, length bands | `sandbox splits build`, `sandbox splits audit`, `sandbox splits show`; `config/splits/families.yaml`; `config/splits/runbook-v1/` | Built and audited offline (seed 20261118, revision bc9eab28). The audit rebuilds from the seed and compares every id file, look complement and `assignments.jsonl` row |
| R00 → every later run | `dataset: {split: all, draw: ranked, exclude_ids_file: config/splits/runbook-v1/<set>.exclude.ids, limit: N}` | Verified to select exactly the set's ids (dev 900, dev-look1 300) |
| R01 pins + served provider | `config/provider_pins.yaml`, `scripts/refresh_provider_pins.py` (`--write-order` pins endpoint `tag` slugs, exits 1 and writes nothing on a failed lookup), `SANDBOX_SERVED_LOG=<file>` | Hook installed at activation for the wrapped `retry_chat_completion` calls; each ledger row carries `status: verified / unverified / mismatch`; `order` empty until the endpoints are chosen |
| R02 statistics | `mailroom_sandbox.experiment_stats`: exact McNemar (exact past 1,024 discordant pairs), paired macro-F1 swap permutation, sign-flip permutation (rejects NaN scores), Holm, sequential-look keep rule, cost-weighted error, Brier/ECE null floors; Clopper-Pearson / ECE / Brier / AUROC re-exported from the Dojo | Unit-tested |
| Offline corpus access | `corpus.load_hf_rows` falls back to the local HF cache for a pinned sha | Preflight and prepare work with `HF_HUB_OFFLINE=1` once both the `default` and `ground_truth` shards of the pin are cached (`sandbox datasets pull`); an uncached `ground_truth` shard is refused, not read as blind rows |
| R00+ label readiness | `sandbox schemas build`, `sandbox schemas build --check`, `sandbox schemas show`; `config/extraction/subclass_schemas.json` | Per-class and per-subclass field schemas graded against Hub + interim + near-gold truth (finding 15) |
| Prompt and schema alignment | `job.schema_guide: true`; `corporate_records_specialist_condensed_v2`, `correspondence_specialist_condensed_v4` (candidates) | Off by default and hashed only when set; candidates need an A/B on dev before adoption (finding 16) |

## Tasks — Phase 0

### Task 1: Freeze the split (R00)
**Files:** `config/splits/families.yaml`, `config/splits/runbook-v1/*`

- [ ] Review the family groupings (`licensing_ip` is a pooled group of 29 docs; `stock_or_mixed` is scored at 38)
- [ ] If families change: `HF_HUB_OFFLINE=1 sandbox splits build --force` (only before any run uses the split)
- [ ] `HF_HUB_OFFLINE=1 sandbox splits audit` exits 0
- [ ] Commit `config/splits/runbook-v1` (gate: split hashes committed)

### Task 2: Pin models and providers (R01)
**Files:** `config/provider_pins.yaml`, `config/decision_models.yaml`, `config/api_prices.yaml`

- [ ] `python scripts/refresh_provider_pins.py` → choose `order` per chat model (public GET, no spend)
- [ ] `python scripts/refresh_decision_models.py --check` → add Jev 1.14 if the design keeps it
- [ ] Write a 10-doc smoke config per model on `dev-look1` with `job.max_wall_seconds` and `job.api_cost_cap_usd`
- [ ] Human: `sandbox run preflight --config <file>`, then `sandbox run start --config <file> --initials <XX>` with `SANDBOX_SERVED_LOG` set
- [ ] Gate, per smoke model: the ledger holds at least one row per expected wrapped call (10 docs × the model's chat agents), and every row has `status: verified` (non-empty pin, provider observed inside it, served model equal to the requested id or its `canonical_slug`). A model with no rows, an `unverified` row or a `mismatch` row fails the gate. `mismatch: false` alone is not evidence
- [ ] The LangChain contract and merger agents are not wrapped (finding 13): pin them through their route's `model_kwargs` and record their served provider, or leave those agents out of the smoke and log the gap as a deviation. The gate stays blocked for a model whose calls go only through an uncovered path

### Task 3: Scoring harness check (R02)
**Files:** `src/mailroom_sandbox/experiment_stats.py`, a 20-doc hand-check sheet under `reports/`

- [ ] Hand-score 20 docs (class, subclass family, fields) and compare with the Dojo scorer output
- [ ] Gate: scorers reproduce the hand-checked results on all 20

### Task 4: Gold-label audit (R03)
**Files:** `data/labels/review/` (new labels version if gold is wrong on >15%)

- [ ] v0 passes on dev, one per audited lineage (needs initials; see finding 2): the sorter at its production prompt, and each specialist lineage at the starting stem named for it under finding 4. A lineage without a named stem is not audited until it has one
- [ ] Adjudicate ~100 v0-vs-gold disagreements per lineage from those v0 predictions, correspondence first, with dev and pool docs only
- [ ] Owner: build `decisions.jsonl` into the gold catalogs and settle the open `VALIDATION.md` decisions (finding 17); then `sandbox schemas build` and commit the registry

### Task 5: G0 checkpoint
- [ ] QC → REVIEW → STOP: the split audit passes, the R01 smoke gate passes for every smoke model (Task 2), scorers match, the v0 passes and the gold audit are done, `sandbox schemas build --check` passes, and findings 1-17 are resolved or logged as deviations

## Verification

- `sandbox splits audit` exits 0 on the committed split
- `sandbox schemas build --check` exits 0 (registry current, 0 mismatches)
- Focused tests pass: `tests/test_experiment_splits.py`, `tests/test_experiment_stats.py`, `tests/test_provider_pins.py`, `tests/test_refresh_provider_pins.py`, `tests/test_corpus.py`, `tests/test_schema_guide.py`, `tests/test_subclass_schemas.py`, `tests/test_specialist_condensed_prompt.py`, `tests/test_cli_surface.py`, `tests/test_vendor_drift.py`
- Hosted CI (lint, full pytest, 84% coverage, reports and requirements checks) is green on the PR head
- H1-H4 are explicitly confirmed, refuted, or marked "inconclusive — exploratory" in R80

## Deviations log

Append to `reports/experiment_log.jsonl` (sandbox-local) whenever scope, method, data
or the split changes after sign-off, citing this plan's path.
