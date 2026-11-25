# Scoring hotfixes

`src/mailroom_sandbox/scoring_hotfixes.py` corrects scoring defects the experiments cannot wait
for. The scorer is the vendored Dojo pin (`vendor/llm-dojo-scoring`, never edited) plus the
sandbox code that calls it. Each correction has an id (`SHF-NNN`) and is never silent.

## Rules

- **Bound to the code it corrects.** Each fix lists its targets (`module:qualname`) with the
  sha256 of the target's source as written in its module file, or a reviewed data file it reads
  (`file:<repo path>` with the file's sha256). When a vendor refresh or an edit changes a target, the fix is `stale`: it is not applied, and `sandbox run preflight`
  fails on the `scoring_hotfixes` check until the fix is re-validated (update the sha after
  checking the fix still holds) or retired. Patching a target at run time (for example
  `monkeypatch.setattr` in a test) does not change its fingerprint.
- **Dual reported.** A scoring entrypoint scores each row with every fix off (the raw Dojo-pin
  value, under `raw_dojo`) and with the current fixes on (the headline).
  `scoring_hotfixes` names the fixes that were on; `scoring_hotfixes_changed` names the
  headline keys whose value differs.
- **Recorded in every run lock** (`scoring_hotfixes`: the module sha256 and each fix's id and
  target fingerprints). A resume refuses a lock whose set differs, and the executing process
  (local or the Modal job worker) refuses to start when its set differs or a fix is not current.
- **Tracked upstream.** Each fix names where it belongs: a drafted llm-dojo-scoring issue
  (D-N below, not yet filed) or `sandbox` for a defect in this repository's scoring code.

Outside a `hotfixed()` block every scoring-call fix is off, so a scorer that does not opt in gets
the Dojo pin's behaviour unchanged. Three fixes act outside a `hotfixed()` block and are on whenever
they are current: SHF-010 during truth preparation (`gold_labels.apply_near_gold`), SHF-009 in the
Decisions routing contract (`decision_backends`), and SHF-013 in the isolated sorter and
`sorter_reviewer` scoring (`eval/agents.py`, `eval/scoring.py`) and in `sorter_arms`. SHF-013 always
keeps the Hub-truth figures beside its own (`raw_dojo`, `hub_truth`), and its corrections file must
still match the pinned fingerprint when it is read, or scoring stops. SHF-009's `forced_choice` is the forced-choice
answer from the same question-set response, not a second request.

## Fixes

| Id | Layer | Correction | Upstream |
| --- | --- | --- | --- |
| SHF-001 | sandbox | A value predicted on a field the truth documents as absent (`gt_presence: schema_documented_absence`) is a false positive on every class, not only `corporate_record`, and counts as a hallucination. Re-validated at the Dojo `7d69bbd` refresh: `extraction_binary_metrics` now skips a contract's v1 parse-compat keys (`merger_consideration`, `maud_clauses`), which the sandbox's contract scope never restores, so the fix holds unchanged. | sandbox (`extraction_scope`); Dojo D-1 |
| SHF-002 | dojo | A name whose tokens are a strict subset or superset of the truth's (after legal-suffix, "the", honorific and initial removal) is a partial match (token Jaccard), not an exact 1.0. | Dojo D-2 |
| SHF-003 | dojo | Two amounts in different currencies do not match. | Dojo D-3 |
| SHF-004 | dojo | Identifiers equal once every non-alphanumeric character is removed match (`CLM12345` = `CLM-12345`). | Dojo D-4 |
| SHF-005 | sandbox | A row that errored (timeout, parse failure, crash) scores 0 in the run headline instead of leaving the denominator. | sandbox |
| SHF-006 | sandbox | A row with no truth is left out of the run mean and counted (`n_no_truth`) instead of averaging in as 0. | sandbox |
| SHF-007 | sandbox | Class labels compare case- and whitespace-folded; a row without a truth class is unscored; an abstention is its own outcome (scored wrong, routed to review). | sandbox |
| SHF-008 | sandbox | Judge, arbiter and boss rows without a truth verdict are unscored instead of 1.0; a judge parse failure scores 0 with `parse_error`. | sandbox |
| SHF-009 | sandbox | Question set 4.0.0's `document_form`, `abstain`, `subclass_gate` and `truncation_notice` keys are applied: an abstention parks the document and the forced-choice answer is kept under `forced_choice`. | sandbox (`decision_backends.decide`) |
| SHF-010 | sandbox | A near-gold label supersedes a conflicting interim gate gap fill (not an `original_header` fill); the replaced value is kept under `truth_overrides` and scored as raw. Precedence reads the interim overlay the row was prepared with; when that snapshot is not passed and the current overlay's fingerprint differs from the row's, nothing is superseded. | sandbox (owner decision, `data/labels/review/INTERIM_AUDIT.md` step 2) |
| SHF-011 | sandbox | A paired A/B report scores a failed document 0 instead of crediting its partial extraction, and counts failed documents per arm. | sandbox |
| SHF-012 | sandbox | Pipeline items record the final sorter or reviewer subclass and score it jointly with the class on the canonical subclass token, not the Dojo's class-blind raw-string match. | sandbox; Dojo D-5 |
| SHF-013 | sandbox | Isolated `sorter` (`task: isolated`) and `sorter_reviewer` runs score the subclass jointly with the class on the canonical subclass token (`subclass_scored`, `subclass_match`, `subclass_by_class`); an abstention or a failed row is a wrong subclass. A reviewed correction in `data/labels/review/subclass_corrections.jsonl` (`verdict: correct`, matching class and Hub value) replaces the Hub subclass for subclass scoring here and for subclass and unit scoring in `sorter_arms` (H5); the Hub-truth figures stay under `raw_dojo` (`hub_truth` in `sorter_arms`) and `subclass_corrections_applied` counts the corrected documents. | sandbox |
| SHF-014 | retired | Served the pain-point composites from a byte-identical copy of the Dojo's `pipeline/pain_points.py` until the vendored pin shipped it. Retired at the Dojo `7d69bbd` vendor refresh, after `tests/test_pain_points.py` found the vendored module byte-identical to the copy; the copy is deleted and the composites come from the Dojo ([guide](pain-point-composites.md#where-the-scoring-comes-from)). | llm-dojo-scoring #185 (shipped) |

## Truth evidence check

The truth the fixes score against is checked too. `mailroom_sandbox.notebook.label_overlay_grounding`
reads every populated truth label of the near-gold overlay (`data/labels/gold-overlay/`, which
SHF-010 lets supersede interim gap fills) and the interim overlay (`data/labels/interim/`), and
checks each one by the rule that admitted it:

| Label | Rule |
| --- | --- |
| A stored quote | The label gate's value rules (`gold_labels.evidence_support`): a whole date in one quote, money by value, token coverage for names and free text, the closed-label vocabulary and the per-field rules. The quote-length caps are not applied: a long `To:` header line is still evidence. |
| Reviewed (`review`) | The review file's rule (`interim_labels`): header lines for `original_header`, the record quote for `review_read_record`, the vocabulary alone for a reviewed intent (an optional quote is not held to the gate's minimum). |
| `derived` | Recomputed from the record's own `doc_subclass`. |
| A closed label with no quote | The value is in the field's vocabulary (`in_vocabulary`). |
| A gap fill or CUAD correction with no quote | The build's rule, against the document's Hub row when one is supplied (`rows`, bound by `doc_sha256`): every token in the text, or agreement with the row's CUAD spans. A gap fill whose stored support is under the admission threshold is `ungrounded` first, with or without the row. Otherwise `no_evidence`. |

Interim `disputed` labels are not truth and are not checked. `tests/test_notebook.py` fails on any
unsupported label. Pytest never reads `data/cache`, so in CI the 803 interim gap fills and CUAD
corrections stay `no_evidence`. Notebook 02 passes `cached_doc_rows()`: after
`sandbox datasets pull` it checks those against their documents as well, and asserts none fails.
At the current pin every truth label passes (gold-overlay 3270 supported, 876 in vocabulary;
interim 3651 supported, 55 in vocabulary).

## Merged truth and precedence

A run's truth is the Hub label, then the interim truth label, then near-gold, each filling only
fields the layers before it leave unlabelled; an interim correction replaces the Hub value it names,
and SHF-010 lets reviewed near-gold replace a conflicting interim gate gap fill (never a reviewed
`original_header` fill). `mailroom_sandbox.notebook.merged_truth` runs that merge
(`interim_labels.apply_overlay`, then `gold_labels.apply_near_gold`) over Hub rows and returns, per
scored field, the layer it came from (`breakdown()`), every document and field both overlays label
with whether they agree and which layer won (`overlaps`), and any result the precedence forbids
(`violations`). `tests/test_notebook.py` covers each source, each overlap outcome and a leaked
overlay; notebook 02 runs it over the pulled Hub corpus and asserts no violation.

At the current pin (3,302 documents) the Hub labels 68,702 fields, of which interim corrections replace 55, and the overlays fill 10,710 more:

| Class | Hub | Interim | Interim correction | Near-gold | Near-gold (SHF-010) |
| --- | --- | --- | --- | --- | --- |
| contract | 12,799 | 45 | 0 | 900 | 0 |
| corporate_record | 5,457 | 980 | 0 | 826 | 36 |
| correspondence | 20,795 | 2,365 | 55 | 4,925 | 4 |
| insurance_claim | 26,100 | 536 | 0 | 0 | 0 |
| merger_agreement | 3,496 | 93 | 0 | 0 | 0 |

The two overlays overlap on 2,450 document fields: 647 agree; 40 interim gate fills differ and
near-gold wins (SHF-010); 1,763 reviewed `original_header` fills differ and win. In 1,692 of those
near-gold read the field as absent, because the corpus text lost the email header the fill quotes;
in the other 71 it read a sign-off or the person a reply addresses. The header value is right, but
the model sees only the text, so those correspondence `sender` / `recipient` /
`additional_recipients` / `communication_date` fields are scored against values not in its input
until the dataset restores the headers. No precedence violation.

Hub labels are not all right, so a conflict with one is evaluated, and the clear winner is the
truth. An overlay replaces a Hub value only as an interim `correction`: a reviewed read of the
message (`review_read_message`, 55 intents) or the Hub's own CUAD evidence (`cuad_party_spans`,
`cuad_agreement_date`, 45 contract fields). A gate extraction that merely disagrees is `disputed`:
it is not truth, the Hub value stands, and `merged_truth(...).hub_conflicts` lists it with both
values and whether the text holds each, for review. At the current pin there are 30: 17
correspondence intents, where the text cannot settle a class and a review read is needed, and 13
contract or merger fields whose Hub truth the Dojo derives from CUAD spans (bare party names where
the gate adds descriptors, renewal clauses CUAD does not tag as a Renewal Term, clause lists, one
merger consideration). Settling one goes through a review file (`data/labels/interim/README.md`),
which makes the winner a `correction` and records who decided it.

## Draft Dojo issues (not filed)

- **D-1** `extraction_binary_metrics` treats a documented-absent field as a hallucination only
  for `corporate_record`.
- **D-2** `score_name_field` scores a token subset or superset of the truth name as an exact match.
- **D-3** `score_money_field` ignores the currency.
- **D-4** `score_id_field` does not normalize separators.
- **D-5** `pipeline_subclass_match` compares raw subclass strings and ignores the class.

Filing these upstream is an owner decision. When the Dojo pin ships a fix, retire the matching
`SHF` entry in the same change that refreshes `vendor/llm-dojo-scoring`.
