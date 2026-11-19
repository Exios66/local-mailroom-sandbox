---
title: "Mailroom sorter and extraction evaluation runbook — research plan"
type: plan
created: 2026-11-18
updated: 2026-11-18
status: draft  # becomes pre-registered once hypotheses H1-H5 and their falsification criteria are signed off
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
| H5 | A Decisions-API model acting as the sorter is non-inferior to the production LLM sorter (v0) on class macro-F1 (margin 2 pts) and subclass-unit accuracy (margin 4 pts), at lower cost per 1,000 documents | class macro-F1 difference (B − A), paired bootstrap one-sided 95% lower bound | On the full 1,000 held-out (R70b), any of the three tests fails after Holm across H5's own family (2 NI tests + lower cost, per finalist): macro-F1 lower bound ≤ −2 pts, unit-accuracy lower bound ≤ −4 pts, or the bootstrap p for "B costs less per document" ≥ 0.05. Details: [H5](#h5-decision-model-as-sorter-sand-108) |

Stop criteria: per lineage — target met, maximum versions, or 5 rounds with nothing
kept. Held-out is unsealed once (R70-R72); nothing is re-run after unsealing.

## Runbook audit (evidence from this checkout, 2026-11-18)

Arithmetic checks that hold: R13 (6 × 300 = 1,800), R15 (900 + 1,200 = 2,100), R20
(4,500 + 2,700 + 2,700 + 900 = 10,800; ~$24 at the design's per-1,000 prices), R32
(5,400; ~$21), R50 (2,500-6,000; $9-22), split sizes (900 + 1,000 + 1,000 + 402 = 3,302).

| # | Row | Finding | Effect | Proposed resolution |
| --- | --- | --- | --- | --- |
| 1 | R70, R73 | Sorter prompts v1-v5 were tuned on the HF `train` split (2,979 docs; `config/production/excluded-ids.txt` header). Only 309 corpus docs are never-tuned (test split minus the tuning list). R73's reason ("no never-tuned docs remain") is not exact. | A 1,000-doc held-out is ~70% in-sample for the sorter lineage, so R70 overstates generalization. | A leak component is ranked by its most-exposed member, so held-out holds no tuning-list document and nothing linked to one (audit gate). It seats the 305 never-tuned docs not linked to a tuning-list doc, then 695 untuned train docs. The other 4 never-tuned docs share a component with tuning-list docs and sit in dev. **Decided (1):** H1's primary test is the 305-doc never-tuned subset (detectable gain ≈ 5 pts at 80% power), with the full 1,000 as secondary. The design's "309" counted the 4 linked docs, which cannot enter held-out without leaking. |
| 2 | R03, G0 | The gold audit needs v0-vs-gold disagreements, but v0 first runs on dev in R20 (Phase 2). | G0 cannot close with only offline work. | **Decided (2):** a v0 sorter pass on dev joins Phase 0 (900 Qwen3.7 Flash calls, ≈ $0.92 with the long-prompt tiers; caps $1.50, `config/runs/rb1-r03-sorter-v0-dev.yaml`). The owner launches it with initials at the spend gate. Audit dev and pool docs only, never held-out. |
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
| 17 | R03 | `data/labels/review/decisions.jsonl` was not built into the gold catalogs (the label pass files are not in this checkout), and two owner decisions in `data/labels/review/VALIDATION.md` were open: interim-over-reviewed-gold precedence and 52 Hub correspondence intents judged wrong. | The registry's counts reflect the overlays as committed; gold changes after adjudication move them. | **Resolved 2026-11-18.** The intents are interim corrections (issue 2). `scripts/gold_labels.py review` applied `decisions.jsonl` and `decisions_supersede.jsonl` to the catalogs in place, without the label passes; reviewed gold now supersedes the interim gap fills it contradicts (`scripts/interim_labels.py check --prune`, issue 1); the registry was rebuilt and `--check` passes. Rebuild with `sandbox schemas build` after any label change; `--check` fails on a stale registry. |
| 18 | R13, R70 (H5) | The decision lineage is not unseen on held-out: `reviewer-validation-luna-decisions-v2-test` and `-v3.0.0-test` scored all 323 HF `test` docs, which are the 305 never-tuned held-out docs plus 18 dev docs (`LINEAGE.yaml`; per-doc answers in `data/handoff/sorter-qwen3.7-flash/test.targets.jsonl` `reviewer_evidence`), and the 3.0.0 test findings shaped 3.1.0, the parent of 4.0.0. | A never-tuned-only H5 test would favour arm B; the 695 train docs favour arm A (sorter tuned on `train`). | H5's confirmatory set is the full 1,000 with both exposure strata reported ([H5](#h5-decision-model-as-sorter-sand-108)). |
| 19 | R13, R60-R62 | `decision_backends.decide` reads only `doc_type`, `subclass` (choice or markers), `verdict`, `handoff` and `max_input_chars`. 4.0.0's `document_form`, `abstain`, `subclass_gate` and `truncation_notice` are loaded but never asked or applied. | Runs with 4.0.0 measure forced-choice class and subclass answers only; no abstention or parking is measured. | Recorded for H5, where forced choice is the like-for-like comparison with the sorter. Implementing the 4.0.0 keys is an open decision-lineage task (owner), and it needs a new run of any figure that depends on them. |

## What this change adds (Phase 0 pathways)

| Runbook row | Command / module | Status |
| --- | --- | --- |
| R00 split, families, leak audit, length bands | `sandbox splits build`, `sandbox splits audit`, `sandbox splits show`; `config/splits/families.yaml`; `config/splits/runbook-v1/` | Built and audited offline (seed 20261118, revision bc9eab28). The audit rebuilds from the seed and compares every id file, look complement and `assignments.jsonl` row |
| R00 → every later run | `dataset: {split: all, draw: ranked, exclude_ids_file: config/splits/runbook-v1/<set>.exclude.ids, limit: N}` | Verified to select exactly the set's ids (dev 900, dev-look1 300) |
| R01 pins + served provider | `config/provider_pins.yaml`, `scripts/refresh_provider_pins.py` (`--write-order` pins endpoint `tag` slugs, exits 1 and writes nothing on a failed lookup), `SANDBOX_SERVED_LOG=<file>` | Hook installed at activation for the wrapped `retry_chat_completion` calls; each ledger row carries `status: verified / unverified / mismatch`; `order` empty until the endpoints are chosen |
| R02 statistics | `mailroom_sandbox.experiment_stats`: exact McNemar (exact past 1,024 discordant pairs), paired macro-F1 swap permutation, sign-flip permutation (rejects NaN scores), Holm, sequential-look keep rule, cost-weighted error, Brier/ECE null floors; Clopper-Pearson / ECE / Brier / AUROC re-exported from the Dojo | Unit-tested |
| Offline corpus access | `corpus.load_hf_rows` falls back to the local HF cache for a pinned sha | Preflight and prepare work with `HF_HUB_OFFLINE=1` once both the `default` and `ground_truth` shards of the pin are cached (`sandbox datasets pull`); an uncached `ground_truth` shard is refused, not read as blind rows |
| R00+ label readiness | `sandbox schemas build`, `sandbox schemas build --check`, `sandbox schemas show`; `config/extraction/subclass_schemas.json` | Per-class and per-subclass field schemas graded against Hub + interim + near-gold truth (finding 15) |
| Prompt and schema alignment | `job.schema_guide: true`; candidates `corporate_records_specialist_condensed_v2`, `correspondence_specialist_condensed_v4`, `contracts_specialist_condensed_v1`, `insurance_claims_specialist_condensed_v5` (#280 is vendored), each parented on its frontrunner (decision 3); `job.specialist_subclass` (`none` / `gold` / `sorter`) names the subclass an isolated run's handoff carries, so `cms_source_table` and the corporate `record_type` are derived as in the pipeline | Off by default and hashed only when set; candidates need an A/B on dev before adoption (finding 16) |

## Tasks — Phase 0

### Task 1: Freeze the split (R00)

**Files:** `config/splits/families.yaml`, `config/splits/runbook-v1/*`

- [ ] Owner sign-off on the 8 groupings in `config/splits/families.yaml` (decision 8; listed in the Discussion reply): contract `licensing_ip` (pooled, 29), `supply_distribution` (55), `services_outsourcing` (66), `alliances_jv` (49), `marketing_sponsorship` (75); corporate_record `governance_instruments` (59); correspondence `legal_demand_rare` (pooled, 3); merger_agreement `stock_or_mixed` (38)
- [ ] If families change: `HF_HUB_OFFLINE=1 sandbox splits build --force` (only before any run uses the split)
- [x] `HF_HUB_OFFLINE=1 sandbox splits audit` exits 0 (re-checked 2026-11-18 on main after #342; `scripts/check_g0.py` runs it)
- [x] Commit `config/splits/runbook-v1` (gate: split hashes committed; landed with #342)

### Task 2: Pin models and providers (R01)

**Files:** `config/provider_pins.yaml`, `config/decision_models.yaml`, `config/api_prices.yaml`

- [x] `python scripts/refresh_provider_pins.py` → choose `order` per chat model (public GET, no spend). Owner choice 2026-11-18: the first-party or full-precision endpoint, no fallbacks: Qwen3.7 Flash `alibaba` (its only endpoint), Qwen3.5-9B `deepinfra/bf16`, DeepSeek V4.1 Flash `deepseek`, GLM 5.3 FlashX Legal `z-ai/fp8` (its only endpoint). A served display name (`DeepInfra`, `Z.AI`) matches a tag on its provider part (`provider_pins.provider_in_order`)
- [x] `python scripts/refresh_decision_models.py` and `scripts/refresh_api_prices.py` (2026-11-18); Jev 1.14 is a decision `candidate_models` entry
- [x] Write a 10-doc smoke config per model on `dev-look1` with `job.max_wall_seconds` and `job.api_cost_cap_usd`: `config/runs/rb1-r01-smoke-<stem>.yaml` for the 4 chat models (`task: pipeline`, 2 docs per class so every specialist runs, judge and boss on the same model) and the 2 named Decisions models (`gpt-6-luna-decisions`, `jev-1.14`; `task: sorter_reviewer`). Total ≈ $0.74 list, above the runbook's "<$0.10" because 2 long merger agreements make up ~70%; the owner accepted it (2026-11-18). Finding 12: the 4 chat models are certain; the other 10 (R13/R60 "6 vendor picks", R62 "Decider V1.2") are not named anywhere yet, so only luna and Jev 1.14 have smoke configs
- [ ] Human: `sandbox run preflight --config <file>`, then `sandbox run start --config <file> --initials <XX>` with `SANDBOX_SERVED_LOG` set
- [ ] Gate, per smoke model: the ledger holds at least one row per expected wrapped call (10 docs × the model's chat agents), and every row has `status: verified` (non-empty pin, provider observed inside it, served model equal to the requested id or its `canonical_slug`). A model with no rows, an `unverified` row or a `mismatch` row fails the gate. `mismatch: false` alone is not evidence
- [x] The LangChain contract and merger agents are not wrapped (finding 13): pin them through their route's `model_kwargs` and record their served provider, or leave those agents out of the smoke and log the gap as a deviation. The gate stays blocked for a model whose calls go only through an uncovered path. Done: activation swaps `langchain_agents.base_agent.ChatOpenAI` for a pinned, recorded subclass (`call_path: langchain`), which also covers the production sorter (it inherits the same base and was unpinned too); Decisions calls are recorded (`call_path: decisions`). Still uncovered: modules that imported `retry_chat_completion` before activation (PDF transcriber) and Responses-API or streamed LangChain calls (unused by the vendored agents); the gate fails on their missing rows
- [ ] Gate script: `scripts/check_r01_smoke.py --ledger data/runtime/rb1-r01/served-<stem>.jsonl --config config/runs/rb1-r01-smoke-<stem>.yaml` exits 0 per model

### Task 3: Scoring harness check (R02)

**Files:** `src/mailroom_sandbox/experiment_stats.py`, a 20-doc hand-check sheet under `reports/`

- [x] Build the 20-doc sheet: `scripts/build_scorer_handcheck.py --draft` writes `reports/campaigns/rb1/rb1-r02-scorer-handcheck/` (4 docs per class from dev, the saved Qwen3.7 Flash sorter pass plus four perturbation profiles, 213 rows). Provenance records both halves of finding 3: labels commit e90ac8b9 and the Dojo pin 025400f3 (0.30.1). Finding 3 is stale: 20 label files changed since e90ac8b9, not only `data/labels/review/*`
- [ ] Human: confirm or correct each of the 205 `agent-draft` scores and fill the 8 blank partial-credit rows, replacing `agent-draft` with initials
- [ ] Gate: `scripts/check_scorer_handcheck.py` exits 0 (scorers reproduce the hand-checked results on all 20). Today it exits 2: every draft matches the scorers, 8 rows are blank
- [ ] Owner: a cost matrix for `experiment_stats.cost_weighted_error` (none is committed; the R02 audit found every other metric covered)

### Task 4: Gold-label audit (R03)

**Files:** `data/labels/review/` (new labels version if gold is wrong on >15%)

- [ ] v0 passes on dev, one per audited lineage (needs initials; see finding 2): the sorter at its production prompt, and each specialist lineage at the starting stem named for it under finding 4. A lineage without a named stem is not audited until it has one
  - Estimated list cost on Qwen3.7 Flash, priced per dev document from the saved pass's prompt tokens with the long-prompt tiers, assuming ~2k extraction output tokens per specialist call: sorter $0.92 (900 docs); insurance $0.11 (229), correspondence $0.09 (198), corporate $0.16 (153), contracts $0.30 (243, 18 over 32k), merger $0.52 (59, 58 over 32k). All five specialist passes ≈ $1.18; with the sorter ≈ $2.10. Each pass gets its own config with `job.max_wall_seconds` and `job.api_cost_cap_usd` at ~1.5× its estimate
  - Specialist v0 passes run with `job.pipeline_handoff: true` and `job.specialist_subclass: gold`, so the subclass-derived fields (`cms_source_table`, corporate `record_type`) follow the pipeline; those fields copy the truth there and are left out of the disagreement sample
- [x] v0 configs: `config/runs/rb1-r03-sorter-v0-dev.yaml` and `rb1-r03-{insurance,correspondence,corporate,contracts,merger}-v0-dev.yaml` (one `strata` bucket per class: 233 / 205 / 156 / 247 / 59 dev docs on the current split; the counts above predate the class-gate rebuild). All pass preflight offline. Merger runs with `specialist_subclass: none`, because the spec refuses `gold` for it; `schema_guide` stays off for v0
- [x] Sheet tooling: `scripts/build_gold_audit_sheet.py --run <run> --lineage <name> --n 100 --seed 20261118` writes `data/labels/review/r03-<lineage>-audit.csv` (dev and pool only; a run holding held-out or calibration ids is refused); `--summarize <sheet>` gives the gold-wrong rate with a Clopper-Pearson 95% interval and the 15% gate (`ambiguous` counts in the denominator, not as gold-wrong)
- [ ] Adjudicate ~100 v0-vs-gold disagreements per lineage from those v0 predictions, correspondence first, with dev and pool docs only
- [x] Owner: build `decisions.jsonl` into the gold catalogs and settle the open `VALIDATION.md` decisions (finding 17); then `sandbox schemas build` and commit the registry (done 2026-11-18, delegated: see `data/labels/review/VALIDATION.md`)

### Task 5: G0 checkpoint

- [ ] `HF_HUB_OFFLINE=1 python scripts/check_g0.py` exits 0. It runs every gate below and reports missing evidence (no ledger, no sheet) as a failure
- [ ] QC → REVIEW → STOP: the split audit passes, the R01 smoke gate passes for every smoke model (Task 2), scorers match, the v0 passes and the gold audit are done, `sandbox schemas build --check` passes, and findings 1-17 are resolved or logged as deviations

## H5: decision model as sorter (SAND-108)

Experiment keys `rb1-r13b` (dev screen) and `rb1-r70b` (sealed confirmatory). Outputs go under
`reports/campaigns/rb1/<key>-sorter-vs-decision/{analysis,figures}/`, each file named from its key.

**Arms.** A is the LLM sorter at its production prompt (`task: isolated`): `rb1-r03-sorter-v0-dev`
(formerly `runbook-r03-sorter-v0-dev`) on dev, and R70's v0 arm on held-out. B is a Decisions-API
model as the sorter: `task: sorter_reviewer`, `reviewer.backend: decisions`, question set
`reviewer_decisions_v4.0.0` (no `handoff:`, so `decide()` classifies from the document alone, one
request per document). No new task was needed. That task already has preflight, lock hashing of the
question set, `uses_openrouter` / `api_budget` coverage (usage goes through `pipeline.limits.record_usage`),
a mock path, and `call_path: decisions` ledger rows. The R01 gate counts one `decisions` row per
document (`check_r01_smoke.expected_calls`, tested for each H5 config). Both arms are scored by
`mailroom_sandbox.sorter_arms` against the same locked truth: class, exact subclass, and subclass
at its split unit (`experiment_splits.unit_correct`). A failed call counts as wrong. Both are priced
the same way: item tokens × `job.metrics.call_cost` (`api_prices.yaml` tiers; Decisions models at
their `decision_models.yaml` input-only price). The provider-reported Decisions cost is shown as a
check.

**Readout.** `scripts/compare_sorter_arms.py --a <A> --b <B> [--b ...] --set <set>
[--volume-docs-per-month N] [--json] [--experiment-key rb1-r13b --write]`. It pairs documents by id
and refuses: unpaired runs, different dataset revisions, differing truth, mock runs, a handoff
question set, and held-out documents outside `--confirmatory`. `--confirmatory` needs a held-out
`--set` and sealed run ids `rb1-r70*`..`rb1-r72*`. Per arm, it reports class accuracy, macro-F1,
per-class F1, subclass and unit accuracy, ECE beside its null floor, Brier, AUROC, latency p50/p95,
total cost, cost per 1k documents, and cost per correct document. Per B arm, it reports: the paired
macro-F1 swap permutation, exact McNemar on class and on unit, paired-bootstrap 95% CIs (accuracy,
macro-F1, unit, cost per document and per 1k), one-sided non-inferiority tests, monthly cost with
CI, and point differences per exposure stratum. With more than two runs it adds a cost-quality
frontier with dominance. Seeds are 20261118 (2,000 bootstrap draws, 5,000 permutations).

**Confirmatory set: the full 1,000 held-out (decision 10, proposed).** Finding 18 means the 305
never-tuned docs are not unseen for B, so they favour B. The 695 `train_untuned` docs favour A,
since the sorter lineage was tuned on `train`. The full set mixes both. Power also points to the
full set: at 305 docs the macro-F1 test has about 27% power. Both strata are reported beside the
primary result. The claim is called robust to exposure only if the `train_untuned` point estimate
also lies above −2 pts, the stratum biased against B. This differs from H1, whose primary result
is the 305 subset, because H1 measures the sorter lineage's own generalization.

**Multiplicity.** H5 has its own Holm family, separate from R70's H1 family. It is a different
claim, and joining the families would cut H1's pre-registered power. The family holds 3 tests per
finalist: NI macro-F1, NI unit, and lower cost. With at most 2 finalists, that is at most 6 tests.
The permutation test and both McNemar tests form a separate, secondary Holm family. The R13b dev
screen is exploratory and has no multiplicity claim (as finding 14).

**Power (`sorter_arms.noninferiority_n` / `noninferiority_power` / `simulate_macro_f1_se`).** The
inputs come from dev on the saved Qwen pass: class accuracy 0.949 and unit accuracy 0.68 (Hub
labels). Planning discordance is 0.06 for class and 0.20-0.30 for unit.

| Set | n | macro-F1 SE | NI macro-F1 power (δ = 0 / B +2 pts) | NI unit power, margin 4 pts (d = 0.20 / 0.30) |
| --- | --- | --- | --- | --- |
| held-out | 1,000 | 0.0093 | 0.69 / 0.99 | 0.88 / 0.75 |
| never-tuned | 305 | 0.0195 | 0.27 / 0.64 | 0.47 / 0.36 |
| dev-look1 | 300 | 0.0175 | 0.31 / 0.74 | 0.46 / 0.35 |

Powers are one-sided at α 0.05, before Holm. A 2-pt margin on unit accuracy would need about
3,900 docs, which is why the unit margin is 4 pts. If B is truly equal to A, the 2-pt macro-F1
margin gives only about 0.69 power on 1,000 docs. A 3-pt margin would give about 0.94 (owner
decision 11). Both margins are fixed before R70b. dev-look1 is a screen, not a test.

**Screen (R13b, inside R13/R60).** The 2 named decision models run on dev-look1: lineage model
`openai/gpt-6-luna-decisions` and candidate `typesafe/jev-1.14` (262k context; its largest
dev-look1 doc is about 126k tokens, so nothing is truncated). Other supported models in
`decision_models.yaml` are optional additions, but their configs are not written until the owner
names them (finding 12): `perplexity/pplx-decider-v1.2` ($0.02/M, about $0.10 per 300 docs),
`google/gemini-decision-1` ($0.10/M, about $0.50), `upstage/solar-decide` ($0.05/M, about $0.25),
and `liquid/d1.2` ($0.02/M, but its 65k context truncates long docs). G6 keeps at most 2 finalists,
by the dev frontier and the NI lower bounds, before held-out is unsealed.

**R65 (load test).** The kept finalist joins the 10x burst. Both arms report p95 latency and the
429 rate. Latency comes from `items.jsonl` `latency_ms`, and 429s from the run's events. A
finalist that breaks G6b limits is dropped, never re-scored. **R80 (readout).** R80 reports the
cost-quality frontier table and the H5 verdict per finalist from the `rb1-r70b` comparison JSON,
with strata and both cost figures.

| Row | Run | Set (n) | Models | Calls | Est. cost (list) | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| R13b | `rb1-r13b-decision-sorter-{luna,jev-1.14}-dev-look1` (caps $0.80 / $0.35) | dev-look1 300 | Luna, Jev 1.14 | 600 | ≈ $0.71 (Luna $0.50, Jev $0.21; $0.63 by chars/4). Arm A reuses R03 (no new calls; about $0.29 of R03's 900-doc $0.92 covers these 300) | Decisions calls validate, 300 `decisions` ledger rows per model, comparison report written; ≤ 2 finalists recorded |
| R70b | `rb1-r70b-decision-sorter-luna-heldout` (SEALED template; cap $2.50), one copy per finalist | held-out 1,000 | ≤ 2 finalists | ≤ 2,000 | Luna ≈ $1.64, Jev ≈ $0.69 per finalist (≤ $3.28). Arm A reuses R70's v0 run (no new calls) | Pre-registered H5 test, own Holm family; nothing re-run after unsealing |

Costs use the saved Qwen pass's prompt tokens per document, minus about 2.3k sorter-prompt tokens,
plus about 4k question tokens. The Decisions API bills input only.

**Held-out seal (`mailroom_sandbox.heldout_seal`).** Preflight (and `run start`, which re-runs it)
refuses any draw through `heldout.exclude.ids` unless two conditions hold: the run id matches
`rb1-r70*`..`rb1-r72*`, and the shell sets `SANDBOX_UNSEAL_HELDOUT` to exactly that run id. It also
refuses, and deletes the prepared file, when another split-exclusion draw prepares held-out rows.

**Open owner decisions.** (10) Full-1,000 primary with strata, as above. (11) The macro-F1 margin,
2 pts or 3 pts. (12) The unit margin, 4 pts. (13) Which extra decision models R13b screens.
(14) Whether arm A at R70b is v0 only, or v0 and the final sorter (the final would be a secondary
comparison in the same H5 family).

## Verification

- `sandbox splits audit` exits 0 on the committed split
- `sandbox schemas build --check` exits 0 (registry current, 0 mismatches)
- Focused tests pass: `tests/test_experiment_splits.py`, `tests/test_experiment_stats.py`, `tests/test_provider_pins.py`, `tests/test_refresh_provider_pins.py`, `tests/test_corpus.py`, `tests/test_schema_guide.py`, `tests/test_subclass_schemas.py`, `tests/test_specialist_condensed_prompt.py`, `tests/test_cli_surface.py`, `tests/test_vendor_drift.py`, `tests/test_sorter_arms.py`
- Hosted CI (lint, full pytest, 84% coverage, reports and requirements checks) is green on the PR head
- H1-H5 are explicitly confirmed, refuted, or marked "inconclusive — exploratory" in R80

## Deviations log

Append to `reports/experiment_log.jsonl` (sandbox-local) whenever scope, method, data
or the split changes after sign-off, citing this plan's path.

### 2026-11-18: rb1 batch 1 configured before G0 closes

- **Owner direction.** On 2026-11-18 the owner directed that the Phase 1 pilots run before G0
  closes. Batch 1 is R11, R12, R14, R15 and the finding-16 prompt A/Bs, 37 configs under
  `config/runs/rb1-*.yaml`, launched by `scripts/rb1_launch_batch1.sh`. R13 is not in the batch.
  Every config draws only dev or the rotation pool; none can select a held-out or calibration id.
- **R12 runs on dev-look1, not the pool.** The pool holds only correspondence and insurance, so
  the five specialists v0 run on the dev-look1 class buckets with the R03 settings. This lets
  field ICC be computed against R03. R11 and R14 stay on the pool, so they cover two classes only.
- **R15 caps are head + tail windows.** `max_input_chars` keeps a head and a tail window
  (`base_agent.truncate_input`, 40% tail), at 4 characters per token. It is not a first-N-token
  cut. R15 scores the 298 long dev + pool documents (`config/splits/rb1/r15-long.ids`, built by
  `scripts/rb1_build_selections.py`) and reports that stratum on its own.
- **R14 settings are provisional.** The two reasoning levels are `none` and `medium`. The
  temp-0 arm that repeats three times is `rnone`. The GLM reasoning-effort pin is not named yet.
  The "best setting" arms for DeepSeek and GLM (R14) and their best-cap arms (R15) wait for the
  Qwen results and are not written.
- **The A/Bs sit under the existing row R41.** They use experiment key `rb1-r41`
  ("Specialist iteration"), so no new campaign row is added. The promotion rule (Holm across the
  four pairs, the keep rule at look 2, no rise in hallucination) is in
  `docs/rb1-prompt-promotion.md`. A look-2 "continue" needs a full-dev look 3, which is an owner
  decision.
- **R11 sorter v0.1** is `sorter_condensed_v6`: one clause change to v5, drawn from dev errors
  only (system and scheduling logs and pasted data tables read as `unknown`). It is paired with
  `rb1-r14-qwen3.7-flash-t0-rnone-rep1` on the same 300 pool documents.
- **Whole-document reads; estimates provisional.** Per the owner's rule, no batch-1 config windows
  or caps a read on the API route: every `max_input_chars` knob is at or above the longest dev or
  pool document of the classes the run draws, and no config sets `job.chunking`. R15's cap arms
  are the one deliberate exception. The estimates assume one call per document per reader and
  stay provisional until the API chunking default (`job.chunking`, auto = off on OpenRouter) lands;
  re-preflight then. `config/splits/rb1/heldout.ids` copies the split's held-out list so the
  preflight held-out seal also checks the R15 draw.
