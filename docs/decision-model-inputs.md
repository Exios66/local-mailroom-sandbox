# Decision model inputs: findings and the 4.1.0 design

2026-11-20. Scope: how the sandbox formats requests for the decision model
(`openai/gpt-6-luna-decisions` on OpenRouter's Decisions endpoint) when it acts as the sorter
or the sorter reviewer, and whether the runbook splits can carry the claims rb1 wants to make.
Sources: the endpoint documentation (listed at the end), `src/mailroom_sandbox/decision_backends.py`,
`config/decisions/` and `config/splits/`. **No API call and no run was made for this document.**
Every number below is computed from committed files; the commands are under
[Reproducing the numbers](#reproducing-the-numbers).

## Summary

- **One real bug.** Every 4.0.x question names `state.document`, but `decide()` sent 4.0.x
  documents as bare text, so that field never existed in the request. 4.1.0 always sends
  `{"document": ...}`.
- **Five weaker spots**, ordered by likely effect: no untrusted-data notice; a form question
  that makes the model find the end of a text of up to 1M characters and pick one defect when
  two can be true; "none of these fits" as an option inside pick-one questions; correspondence
  markers that a denial satisfies; and placeholder thresholds, unrecorded refusals and no
  `session_id`.
- All of them change what the model reads, so they are a new question-set version,
  **4.1.0** (`config/decisions/reviewer_decisions_v4.1.0.yaml`, lineage status `draft`), never
  an edit to 4.0.x. Published sets send byte-identical requests after this change.
- **Splits:** both runbook versions pass every integrity check. They are large enough for
  the 4-point subclass margin and for a 2% per-class error claim on `insurance_claim` and
  `correspondence` only; the 2-point macro-F1 margin needs more paired documents than dev
  holds unless the two arms disagree on fewer than about 4.6% of documents.

## 1. Requirements

### Functional

| Id | Requirement |
| --- | --- |
| F1 | One request per document returns the class, the subclass and the routing evidence (form, abstention) the pipeline needs. |
| F2 | What the questions say about the request is true of the request (field names, what is passed). |
| F3 | A document that cannot be extracted as one complete instrument (cut off, bundled, unreadable, not English) reaches a person. |
| F4 | A question the provider will not answer is visible as a refusal, not as a confident default. |
| F5 | A published question set's request never changes; a change is a new version (`LINEAGE.yaml`). |

### Non-functional

| Id | Requirement | Current figure |
| --- | --- | --- |
| N1 | Cost | $0.10 per 1M input tokens, output free; the exact charge is in each response's `usage.cost`. 4.1.0's questions are 17,977 characters of JSON against 4.0.2's 11,115 (about +1.7k tokens, +$0.00017, per document). |
| N2 | Context | 1.05M tokens; `max_input_chars: 1000000` keeps the largest document whole, and `truncation_notice` records any cut. |
| N3 | Tunable parameters | None on this model: everything is in the state and the question texts. |
| N4 | Calibration | OpenRouter calls the probabilities calibrated. That is the provider's claim, not a measurement on these documents: every threshold here is fitted on our calibration set. |
| N5 | Statistical claims | 2% per-class error at 95% confidence; a 2-point macro-F1 and a 4-point subclass non-inferiority margin (rb1 evaluation design v2). |

### Constraints

- Offline tests only; no paid call is launched by an agent (`CLAUDE.md`).
- SHF-009 fingerprints `apply_question_set_contract`; editing it makes the fix stale and
  every run lock taken under it unresumable. 4.1.0's rules therefore live in a separate
  function (`apply_v41_rules`).
- `dev-look1` is fully tuned and held-out is sealed; neither may be used to fit 4.1.0.

## 2. High-level design

```text
 document text ──► mask_card_numbers ──► window (max_input_chars)
                                              │
                         ┌────────────────────┴───────────────────────┐
                         │ 4.0.x: state = "<bare text>"               │
                         │ 3.x:   state = {document, sorter_handoff}  │
                         │ 4.1.0: state = {document, form_signals}    │◄── form_signals(): length, window cut,
                         └────────────────────┬───────────────────────┘     last 240 chars, <DOCUMENT>/<TYPE>
                                              │                             and "Source:" counts
 decision_questions(qset) ── questions ──────►│◄── session_id = "sandbox-<run_id>" (4.1.0, inside a run)
   4.1.0: untrusted_notice on every question  ▼
          form__* yes/no, fit__<class> yes/no  POST /api/alpha/decisions  (_post_decision: retries, run guard)
                                              │
                                              ▼
                       answers + usage ──► refused_questions (4.1.0) ──► forced-choice reading
                                              │
                                              ▼
                    apply_question_set_contract (SHF-009, unchanged) ──► apply_v41_rules (4.1.0 only)
                                              │
                                              ▼
                 {doc_type, doc_subclass, confidence (0 when parked), abstain_reasons, forced_choice,
                  document_form, document_form_flags, refused_questions, session_id, usage}
```

Components and owners: `decide()` builds the state and reads the answers;
`decision_questions()` builds the question map; `apply_question_set_contract()` is the
fingerprinted 4.0.0 routing contract; `apply_v41_rules()` adds the 4.1.0 rules after it;
`sorter_arms.arm_model()` refuses any set that reads the sorter handoff as a stand-alone sorter.

## 3. Deep dive

### 3.1 The endpoint as documented

- **Request:** a `model`, the content to judge as `state` (plain text, a JSON object, or a
  list with images) and named, typed `questions`: `choice` (pick one of a set of options with
  criteria), `noul` (a yes/no probability), `score` (ordered levels) and `box` (an image
  location). An optional `session_id` (at most 256 characters) groups requests for
  observability and is never sent to the provider.
- **Response:** a probability for every option of every question, and `usage` with the exact
  amount charged. The provider may refuse a single question while answering the rest.
- **Not verified here:** the exact JSON shape of a single refused question. The sandbox
  therefore treats any asked question whose answer is missing, carries a truthy `refusal`,
  `refused` or `error` key, or has no `choice` / `noul` value as refused
  (`refused_questions`). Confirm the shape on the first 4.1.0 smoke and narrow the rule then.

### 3.2 Findings, ordered by likely effect

| # | Finding | Evidence | 4.1.0 change |
| --- | --- | --- | --- |
| 1 | **Bug.** 4.0.x questions say "Classify state.document", "Judge the state of state.document", but `decide()` sends `state` as the bare string when the set has no `handoff` key, which no 4.0.x set has. | `decide()` before this change: `state: Any = document` unless `qset["handoff"]`; `sorter_arms.arm_model` refuses handoff sets as sorter arms, so every decision-as-sorter run (R13b) sent bare text. | `state_shape: object`: always `{"document": ...}`. |
| 2 | No sentence tells the model the document is untrusted data. OpenRouter's examples all carry one, and its model-limits page names text that argues for its own classification as a known weakness. | 4.0.2 question texts. | `untrusted_notice` is prepended to every question. It says the text's titles, headings and content are the evidence, so it does not tell the model to ignore a title. |
| 3 | The form question asks the model to notice a cut-off ending or a second bundled document inside a text of up to 1M characters, and forces one pick although "cut off" and "bundled" can both be true. | 4.0.2 `document_form`; the R13b form calibration's misses were cut-off endings and footer-separated bundles (4.0.2 header). | `form_signals` passes measured facts (length, window cut, the last 240 characters, whether it ends on sentence punctuation, `<DOCUMENT>`/`<TYPE>` and `Source:` counts). `document_form` becomes four yes/no flags: `fragment`, `bundle`, `unreadable`, `non_english`. |
| 4 | "None of these fits" is an option inside every pick-one subclass question (`not_this_class`). OpenRouter's question-design guidance recommends a separate yes/no "does any option fit?" question and says to test both forms. | `decision_questions()` adds `not_this_class` to every subclass pick. | `subclass_fit`: a `fit__<class>` yes/no question per pick-one class; `not_this_class` is dropped (`undetermined` stays). `abstain.subclass_fit_min` replaces `subclass_not_this_class_max`. |
| 5 | Correspondence markers ask whether the text "contains or discusses" a demand, notice and so on. "This is not a demand" satisfies that wording. | 4.0.2 `subclass.correspondence.markers`. | "Contains or discusses" stays (the corpus scores markers anywhere, forwards included), but each negatable marker says a denial does not count. |
| 6 | The park thresholds are placeholders, refusals are not recorded, and runs do not set `session_id`. | 4.0.2 `abstain` comment ("Provisional"); `_post_decision` raises only on a whole-request refusal; no `session_id` in the body. | `record_refusals`: `refused_questions` on every result, and a refused `doc_type` or form flag parks. `session_id: run`. Thresholds stay provisional and are fitted on runbook-v2 calibration (section 4). |

### 3.3 The 4.1.0 request

```json
{
  "model": "openai/gpt-6-luna-decisions",
  "session_id": "sandbox-<run_id>",
  "state": {
    "document": "<masked text, up to 1,000,000 characters>",
    "form_signals": {"characters": 48211, "cut_by_window": false, "ends_with": "<last 240 characters>",
                     "ends_with_sentence_punctuation": true, "document_tags": 0, "type_tags": 0,
                     "filing_source_lines": 1}
  },
  "questions": {
    "doc_type": {"type": "choice", "instructions": "<notice> Classify state.document ...", "criteria": {"...": "..."}},
    "form__fragment": {"type": "noul", "instructions": "<notice> Is state.document only part of ..."},
    "form__bundle": {"type": "noul"}, "form__unreadable": {"type": "noul"}, "form__non_english": {"type": "noul"},
    "subclass__merger_agreement": {"type": "choice", "criteria": {"all_cash": "...", "undetermined": "..."}},
    "fit__merger_agreement": {"type": "noul", "instructions": "<notice> Suppose state.document is a merger_agreement ..."},
    "marker__correspondence__demand": {"type": "noul"}
  }
}
```

20 questions per request (4.0.2: 13). Only the chosen class's subclass and fit answers are
used; the others are asked because the class is not known when the request is built.

### 3.4 Routing (parks)

A parked document has `abstained` and `route_to_human` true, `confidence` 0 and its reasons in
`abstain_reasons`. The forced-choice reading is kept under `forced_choice`.

| Reason | Rule | Where | Threshold |
| --- | --- | --- | --- |
| `doc_type:unknown`, `margin`, `unknown_max` | as 4.0.x | SHF-009 contract | 0.10 margin, 0.34 unknown (provisional) |
| `subclass_gate:<choice>` | `undetermined` or a refused pick, per-class policy (`park` for merger_agreement and corporate_record, `keep_sorter` otherwise) | SHF-009 contract | — |
| `document_form:<flag>` | a form flag's p(yes) ≥ `park_min` | `apply_v41_rules` | 0.50 (provisional) |
| `refused:form__<flag>`, `refused:doc_type` | the question went unanswered; nothing then says the document is intact | `apply_v41_rules` | — |
| `subclass_fit` | the chosen class's `fit__` p(yes) < `subclass_fit_min` | `apply_v41_rules` | 0.50 (provisional) |
| `subclass_gate:fit_unanswered` | `fit__` unanswered while the pick was usable; same per-class policy | `apply_v41_rules` | — |

`document_form` reports the first flag that fired, else `complete_instrument`.
`document_form_human_mass` (read by `decision_figures` and `rb1_form_floor.py`) is the largest
flag probability, because the flags are not exclusive; in 4.0.x it is the summed mass on
`human_forms`. The two are not the same quantity: do not pool them across versions.

### 3.5 Error handling

- Transport errors and 408/429/5xx are retried with backoff inside `_post_decision`; a
  whole-request refusal or any other status raises at once (unchanged).
- Card-shaped digit groups are masked before posting (unchanged); `form_signals` is computed on
  the masked text, so `ends_with` never carries an unmasked number.
- A single refused question no longer disappears: it is listed in `refused_questions`, and the
  routing treats it as unusable (park or gate), never as a confident default.
- A malformed 4.1.0 key (`state_shape`, `session_id`, `document_form_flags`, `subclass_fit`,
  `subclass_fit_min`, or asking both `document_form` and the flags) fails at load, not mid-run.

## 4. Data splits and scale

### 4.1 Integrity

Both `runbook-v1` (dataset `bc9eab28`) and `runbook-v2` (dataset `ff4ca546`, v9.3) hold 3,302
documents: dev 900, calibration 1,000, held-out 1,000, pool 402. Every file hash matches its
manifest, no document is in two sets, and no near-duplicate group (`component`) crosses sets.
Held-out shares no document with the exposure list (`runbook-v2-exposure.txt`, 483 ids), so no
held-out document has been looked at.

### 4.2 What each set can support

- **dev-look1 is not evidence.** We tuned on all 300 of its documents (runbook-v2 marks 285 of
  them `tuned`; the 4.0.1 wording came from its smoke). Use it for smoke runs only.
- **Calibrate on runbook-v2 calibration.** runbook-v1's calibration set contains the 50
  form-calibration draw-1 documents the 4.0.2 wording was written from; runbook-v2 removes them
  (`calibration ∩ formcal-draw1`: 50 in v1, 0 in v2).
- **Do not compare across versions.** The R13b runs ran on v1's dataset (`bc9eab28`, 78
  references in `reports/campaigns/rb1/rb1-r13b-sorter-vs-decision`), while the R13b run
  configs now point at v2 (`ff4ca546`).

### 4.3 Per-class error target (2% at 95%)

Zero-failure one-sided Clopper-Pearson bound: with n error-free accepts, the error rate that
can be certified at 95% is 1 − 0.05^(1/n); 2% needs n ≥ 149.

| Class | runbook-v2 calibration docs | Best certifiable error | Meets 2%? |
| --- | ---: | ---: | --- |
| insurance_claim | 383 | 0.78% | yes |
| correspondence | 356 | 0.84% | yes |
| corporate_record | 122 | 2.43% | no |
| contract | 105 | 2.81% | no |
| merger_agreement | 34 | 8.43% | no |

These are best cases: a single error among the accepts loosens each bound.

### 4.4 Subclass cutoffs, length

- **Subclass units with no calibration document** (runbook-v2): contract Consulting
  Agreements, Distributor, Maintenance, Service and Strategic Alliance; corporate_record
  board_resolution and bylaws; the merger_agreement `stock_or_mixed` family. A per-class
  subclass cutoff cannot be fitted for them from calibration; they keep the `subclass_gate`
  policy.
- **Length:** 55 of 1,000 calibration documents are longer than 32k characters (833 are at
  most 4k). Any length-conditioned claim (long documents, the 1M window) rests on 55 documents.

### 4.5 Sorter vs decision non-inferiority (H5)

Paired comparison on the same documents; one-sided α = 0.025, power 80%; the variance of the
paired difference is approximated by the discordance rate d (the share of documents the arms
disagree on), so n ≈ (1.96 + 0.84)² · d / δ².

| Margin δ | n per unit discordance | d = 6% to 15% | Dev (900) is enough while |
| --- | ---: | ---: | --- |
| 2 points macro-F1 | 19,622 · d | 1,177 to 2,943 | d ≤ 4.6% |
| 4 points subclass | 4,906 · d | 294 to 736 | d ≤ 18.3% |

Macro-F1 is approximated by paired accuracy here; a per-class F1 margin needs more, not fewer,
documents. Measure d on the first paired dev run before committing to the 2-point claim.

## 5. Trade-offs

| Decision | Chosen | Alternative | Why |
| --- | --- | --- | --- |
| Fix the bug in 4.0.x or a new version | New version 4.1.0 | Patch `decide()` for every set | Locked runs must replay exactly (F5); patching would silently change what 4.0.x runs sent. |
| Where the 4.1.0 rules live | `apply_v41_rules` after the SHF-009 contract | Edit `apply_question_set_contract` | Editing it makes SHF-009 stale and every lock under it unresumable. Cost: the 4.1.0 rules are not fingerprinted by a hotfix id; they are pinned by the question set's sha256 in the run lock. Registering them as their own SHF id is a reviewable follow-up. |
| Form question | Four yes/no flags | One pick-one question | Defects are not exclusive; one pick hid the second. Cost: four probabilities to calibrate instead of one mass. |
| "None fits" | Separate `fit__<class>` question | `not_this_class` option | Provider guidance; a forced pick can no longer hide a wrong class. Cost: 4 more questions per request, and a pick with no fitting option may now be refused (recorded). Kept only if an ablation against the option form agrees. |
| Form facts | Computed in code, passed as data | Model reads the whole text | Code finds the last line of a 1M-character text exactly; the model still judges what it means. |
| Refusal rule | Anything that is not a usable answer | Match one documented shape | The single-question refusal shape is not confirmed here; over-counting is visible, under-counting is silent. |
| An unanswered form flag | Parks | Treated as no | Nothing then says the document is intact (F3). |

## 6. Rollout

1. Land 4.1.0 as `draft` (this change): offline tests, byte-identity of every published set.
2. Smoke on a few runbook-v2 calibration documents (operator launch, with spend caps): check
   that `state` is an object, every 4.1.0 question is answered or listed in
   `refused_questions`, `session_id` groups the run in provider logs, and record the refusal
   shape.
3. Fit `park_min`, `subclass_fit_min`, `margin` and `unknown_max` on runbook-v2 calibration;
   compare with 4.0.2 on the same draw under a paired rule fixed before it runs.
4. Ablate the separate fit question against the in-question option before keeping it.
5. Only then a dev comparison with the LLM sorter (H5), with d measured first (section 4.5).

## 7. What to revisit

- The refusal rule, once the real single-question refusal shape is observed.
- Whether `apply_v41_rules` should carry its own scoring-hotfix id.
- Per-class subclass cutoffs where calibration documents exist; more calibration documents (or
  a pooled family) for contract, corporate_record and merger_agreement before any 2% claim.
- A length-stratified calibration draw if long-document claims matter (55 documents today).
- `form_signals`' fixed 240-character tail, if fragments are missed whose cut is earlier.

## Not verified

- No live request was made: the 4.1.0 answers, the refusal shape and `session_id` grouping are
  untested against the provider.
- The question-design guidance (a separate "does any option fit?" question, test both forms)
  and the model-limits note (text that argues for its own classification) come from an earlier
  read of OpenRouter's decisions skill references (question design, model limits); they were
  not re-read for this change and are not re-measured here.
- The non-inferiority sizes use a normal approximation with paired accuracy standing in for
  macro-F1.

## Reproducing the numbers

All offline, from the repository root:

```bash
.venv/bin/python -m pytest -q tests/test_decision_qset_v41.py -n 0 --no-cov   # 4.1.0 request and routing
```

The split digest (integrity, per-class counts and bounds, bands, zero-calibration units,
sample sizes) was produced by a read-only scratch script over `config/splits/` that reads only
the id and assignment files, never document text; its output is quoted in the pull request.

## Sources

- [Decisions request reference](https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-request.md)
- [Decisions questions-and-answers request reference](https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-questions-and-answers-request.md)
- [Decisions request model, TypeScript SDK (`session_id`)](https://openrouter.ai/docs/client-sdks/typescript/models/decisionsrequest.md)
- [Decisions, Python SDK](https://openrouter.ai/docs/client-sdks/python/sdks/decisions/README.md)
