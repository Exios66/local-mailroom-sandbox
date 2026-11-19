# Scoring hotfixes

`src/mailroom_sandbox/scoring_hotfixes.py` corrects scoring defects the experiments cannot wait
for. The scorer is the vendored Dojo pin (`vendor/llm-dojo-scoring`, never edited) plus the
sandbox code that calls it. Each correction has an id (`SHF-NNN`) and is never silent.

## Rules

- **Bound to the code it corrects.** Each fix lists its targets (`module:qualname`) with the
  sha256 of the target's source as written in its module file. When a vendor refresh or an
  edit changes a target, the fix is `stale`: it is not applied, and `sandbox run preflight`
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
the Dojo pin's behaviour unchanged. Two fixes act outside a scoring call and are on whenever they
are current: SHF-010 during truth preparation (`gold_labels.apply_near_gold`) and SHF-009 in the
Decisions routing contract (`decision_backends`). SHF-009's `forced_choice` is the forced-choice
answer from the same question-set response, not a second request.

## Fixes

| Id | Layer | Correction | Upstream |
| --- | --- | --- | --- |
| SHF-001 | sandbox | A value predicted on a field the truth documents as absent (`gt_presence: schema_documented_absence`) is a false positive on every class, not only `corporate_record`, and counts as a hallucination. | sandbox (`extraction_scope`); Dojo D-1 |
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

## Truth evidence check

The truth the fixes score against is checked too. `mailroom_sandbox.notebook.label_overlay_grounding`
reads every populated label of the near-gold overlay (`data/labels/gold-overlay/`, which SHF-010
lets supersede interim gap fills) and the interim overlay (`data/labels/interim/`) and checks the
value against the evidence the label stores, with the label gate's value rules
(`gold_labels.evidence_support`: a whole date in one quote, money by value, token coverage for
names and free text, the closed-label vocabulary). The gate's quote-length caps are not applied:
a long `To:` header line is still evidence. A label with a value and no stored quote (derived
fields, CUAD corrections, closed-label defaults) is counted as `no_evidence`, since it was checked
against the full document when it was built. `tests/test_notebook.py` fails on any unsupported
label outside its short, commented `KNOWN_UNSUPPORTED` list.

## Draft Dojo issues (not filed)

- **D-1** `extraction_binary_metrics` treats a documented-absent field as a hallucination only
  for `corporate_record`.
- **D-2** `score_name_field` scores a token subset or superset of the truth name as an exact match.
- **D-3** `score_money_field` ignores the currency.
- **D-4** `score_id_field` does not normalize separators.
- **D-5** `pipeline_subclass_match` compares raw subclass strings and ignores the class.

Filing these upstream is an owner decision. When the Dojo pin ships a fix, retire the matching
`SHF` entry in the same change that refreshes `vendor/llm-dojo-scoring`.
