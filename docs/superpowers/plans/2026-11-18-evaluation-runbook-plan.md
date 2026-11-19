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
| H3 | Class-specific auto-route gates hold at 2% wrong routes | 95% one-sided Clopper-Pearson upper bound, per class on its own calibration documents (decision 6) | A class's bound ≥ 2% on calibration, or its realized held-out error rate's bound ≥ 2%. A class whose calibration n cannot reach 2% (contract 105, corporate_record 137, merger_agreement 34 docs; 149 error-free accepts needed) reports its own certified bound and is not claimed at 2% |
| H4 | The pipeline reduces human review versus production v0 | review-rate difference, 95% CI | CI includes 0 or the reduction is under 2 pts |

Stop criteria: per lineage — target met, maximum versions, or 5 rounds with nothing
kept. Held-out is unsealed once (R70-R72); nothing is re-run after unsealing.

## Runbook audit (evidence from this checkout, 2026-11-18)

Arithmetic checks that hold: R13 (6 × 300 = 1,800), R15 (900 + 1,200 = 2,100), R20
(4,500 + 2,700 + 2,700 + 900 = 10,800; ~$24 at the design's per-1,000 prices), R32
(5,400; ~$21), R50 (2,500-6,000; $9-22), split sizes (900 + 1,000 + 1,000 + 402 = 3,302).

| # | Row | Finding | Effect | Proposed resolution |
| --- | --- | --- | --- | --- |
| 1 | R70, R73 | Sorter prompts v1-v5 were tuned on the HF `train` split (2,979 docs; `config/production/excluded-ids.txt` header). Only 309 corpus docs are never-tuned (test split minus the tuning list). R73's reason ("no never-tuned docs remain") is not exact. | A 1,000-doc held-out is ~70% in-sample for the sorter lineage, so R70 overstates generalization. | A leak component is ranked by its most-exposed member, so held-out holds no tuning-list document and nothing linked to one (audit gate). It seats the 305 never-tuned docs not linked to a tuning-list doc, then 695 untuned train docs. The other 4 never-tuned docs share a component with tuning-list docs and sit in dev. **Decided (1):** H1's primary test is the 305-doc never-tuned subset (detectable gain ≈ 5 pts at 80% power), with the full 1,000 as secondary. The design's "309" counted the 4 linked docs, which cannot enter held-out without leaking. |
| 2 | R03, G0 | The gold audit needs v0-vs-gold disagreements, but v0 first runs on dev in R20 (Phase 2). | G0 cannot close with only offline work. | **Decided (2):** a v0 sorter pass on dev joins Phase 0 (900 Qwen3.7 Flash calls, ≈ $0.92 with the long-prompt tiers; caps $1.50, `config/runs/runbook-r03-sorter-v0-dev.yaml`). The owner launches it with initials at the spend gate. Audit dev and pool docs only, never held-out. |
| 3 | R02 | "field scorer @ e90ac8b9" names a gold-label commit, not a scorer. The scorer is the vendored Dojo pin (`_VENDOR_PINS`). Gold labels are unchanged since e90ac8b9 (HEAD adds only `data/labels/review/*`). | Ambiguous provenance. | Record both: labels at e90ac8b9 and the Dojo vendor pin. |
| 4 | R12, R40-R42 | No `contracts_specialist_condensed_*` exists (PI-C says "from v3"), corporate-record condensed has only v1 (PI-R says "from v2"), and the "decision v0.4.0" set is `config/decisions/reviewer_decisions_v4.0.0.yaml`, which was committed without a `LINEAGE.yaml` entry. | Those lineages had no named starting version. | **Decided (3):** each specialist lineage starts from its frontrunner as parent, which is also its v0 stem for R03: insurance `insurance_claims_specialist_condensed_v3`, correspondence `correspondence_specialist_condensed_v3`, corporate `corporate_records_specialist_condensed_v1`, contracts `contracts_specialist_v33_simplified`, merger `merger_agreement_specialist_maud_v2` (all in `config/prompts/`), improved to the repaired extraction schema (`config/extraction/subclass_schemas.json`). The decision lineage starts from reviewer_decisions 4.0.0, now registered as a candidate (`test_every_question_set_file_is_in_the_lineage`). |
| 5 | R40, R41 | "7 specialist lineages" vs 5 specialists; PI-M (merger) has 0 iteration versions. | Calls/cost overstated. | **Decided (4):** 5 specialist lineages, 4 iterated (merger is aligned but not iterated); R40/R41 calls and cost scale by 5/7. |
| 6 | R14 | The listed grid gives 3,600 calls (Qwen 6 configs + temperature-0 run 3× = 8 runs × 300; DeepSeek and GLM 2 configs × 300 each), not 4,200. | Budget ambiguity. | **Decided (4):** R14 is 3,600 calls: Qwen 8 runs × 300 = 2,400, DeepSeek 2 × 300 = 600, GLM 2 × 300 = 600. |
| 7 | R15 | A 4K/8K cap only changes documents over 4k tokens. After the class-gate rebuild the pool holds 4 of them (contract, corporate and merger, the long classes, now keep their remainder in calibration); dev holds 294 (163 ≤16k, 50 ≤32k, 81 >32k). | The pool alone cannot power the sweep. | **Decided (5):** score R15 on dev + pool long documents (298). Report the long-document scores as their own stratum, with a separate analysis of their effect on the all-document averages; no long-document figure is folded into a headline mean without that split. |
| 8 | R51, G5 | Dev and held-out quotas (20 per unit) left calibration with 75 contracts and 24 mergers. Certifying 2% at 95% needs ≥149 zero-error accepts. | The global gate would hide per-class error. | **Decided (6): every class gets its own gate.** `families.yaml` `calibration` sets 2% at 95%; a class that cannot fund 149 accepts keeps its whole remainder in calibration (audit gate). Calibration now holds contract 105, corporate_record 137, correspondence 348, insurance_claim 376, merger_agreement 34; best certifiable bounds 2.81%, 2.16%, 0.86%, 0.79%, 8.43% (`sandbox splits show`, `experiment_stats.class_gate_plan`). Reaching 2% for contract and corporate needs smaller dev/held-out quotas for those classes (open, owner). |
| 9 | R00 | The ±5-pt `source_corpus` / `annotation_method` rule conflicts with oversampling small classes (raw gaps 5-8.5 pts). | The rule cannot hold on raw mixes. | Gate within class on dev and held-out (max gap 3.0 pts); report raw and calibration gaps as information. |
| 10 | R00 | Only 23 docs carry `matter_id` / `group_id`. | Thread leakage is not covered by those fields alone. | The leak audit also links correspondence by normalized subject (reply/forward prefixes stripped) and identical normalized text: 24 components, largest 6, none crossing sets. `message_id` / `in_reply_to` / `related_document_ids` are linked when present, but never fire on this corpus (unique message ids, no replies or related ids recorded), so subject is the only thread signal. |
| 11 | All | Insurance claims (1,100) are 100% `synthetic`. The design's "637 correspondence labels are DeepSeek zero-shot" cannot be verified from the Hub (`annotation_model` is empty). DeepSeek is also a transfer target. | Possible label-model bias toward DeepSeek on correspondence; insurance results may not transfer to live traffic. | **Decision 7:** the repaired correspondence labels (52 intent corrections, 1,795 header gap fills from the original maildir headers) came from PR #341, merged into this branch with the registry rebuilt (`sandbox schemas build`): 0 mismatches, 0 problems, 35 correspondence field cells changed. Five subclass verdicts moved: demand and letter `additional_recipients` constant → thin, and demand `communication_date` and `sender` and meeting_request `sender` thin → iterate. Correspondence first in R03; insurance reported separately in R80. |
| 12 | R01 | "all 10 + 4" models is undefined. `typesafe/jev-1.14` is in `config/decision_models.yaml` (this finding said otherwise; corrected 2026-11-18). GLM is priced and profiled under the alias `z-ai/glm-5.3-flashx-legal`, while the design pins `-20261102`. | Smoke test scope and pins are unclear. | **Decision 9:** Jev 1.14 is a `candidate_models` entry in `config/decisions/LINEAGE.yaml` (262k context, below 4.0.0's whole-document window). Both catalogs refreshed 2026-11-18 (`microsoft/microsoft-decision-1.1` added; `qwen3.5-9b`, `deepseek-v4-flash`, `deepseek-v4.1-flash-1017` prices changed). The 14 models still need listing. |
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
| Prompt and schema alignment | `job.schema_guide: true`; candidates `corporate_records_specialist_condensed_v2`, `correspondence_specialist_condensed_v4`, `contracts_specialist_condensed_v1`, `insurance_claims_specialist_condensed_v6`, each parented on its deployed frontrunner (decision 3) | Off by default and hashed only when set; candidates need an A/B on dev before adoption (finding 16) |

## Tasks — Phase 0

### Task 1: Freeze the split (R00)

**Files:** `config/splits/families.yaml`, `config/splits/runbook-v1/*`

- [ ] Owner sign-off on the 8 groupings in `config/splits/families.yaml` (decision 8; listed in the Discussion reply): contract `licensing_ip` (pooled, 29), `supply_distribution` (55), `services_outsourcing` (66), `alliances_jv` (49), `marketing_sponsorship` (75); corporate_record `governance_instruments` (59); correspondence `legal_demand_rare` (pooled, 3); merger_agreement `stock_or_mixed` (38)
- [ ] If families change: `HF_HUB_OFFLINE=1 sandbox splits build --force` (only before any run uses the split)
- [ ] `HF_HUB_OFFLINE=1 sandbox splits audit` exits 0
- [ ] Commit `config/splits/runbook-v1` (gate: split hashes committed)

### Task 2: Pin models and providers (R01)

**Files:** `config/provider_pins.yaml`, `config/decision_models.yaml`, `config/api_prices.yaml`

- [ ] `python scripts/refresh_provider_pins.py` → choose `order` per chat model (public GET, no spend)
- [x] `python scripts/refresh_decision_models.py` and `scripts/refresh_api_prices.py` (2026-11-18); Jev 1.14 is a decision `candidate_models` entry
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
  - Estimated list cost on Qwen3.7 Flash, priced per dev document from the saved pass's prompt tokens with the long-prompt tiers, assuming ~2k extraction output tokens per specialist call: sorter $0.92 (900 docs); insurance $0.11 (229), correspondence $0.09 (198), corporate $0.16 (153), contracts $0.30 (243, 18 over 32k), merger $0.52 (59, 58 over 32k). All five specialist passes ≈ $1.18; with the sorter ≈ $2.10. Each pass gets its own config with `job.max_wall_seconds` and `job.api_cost_cap_usd` at ~1.5× its estimate
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
