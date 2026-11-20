# Decision model inputs: draft 4.2.0 implementation

Question set `reviewer_decisions_v4.2.0.yaml` is an offline-tested draft. It changes
request structure and routing; it is not adopted for live use. Version 4.1.0 remains
the classification-criteria alignment merged in PR #386. Its file and request
body are unchanged. Version 4.2.0 inherits its class and subclass criteria.

The API reference and calibration analysis are in
[Decision model inputs](decision-model-inputs.md). This document describes the
implementation and its remaining acceptance gates.

## Request and answer handling

- The state is an object containing `document` and computed `form_signals`:
  character count, window truncation, last characters, sentence punctuation,
  document/type tag counts and filing-source line counts.
- Every question starts with an untrusted-document notice. Document text remains
  evidence rather than instructions. This wording is a defense to evaluate,
  not a measured guarantee against prompt injection.
- Four independent form questions replace the exclusive form choice: fragment,
  bundle, unreadable and non-English. Every fired flag is recorded. Any fired
  flag or unanswered required form question parks the document.
- Each choice-based subclass question has a separate `fit__<class>` probability.
  True catchalls (`contract.other` and `corporate_record.other`) are excluded from
  the fit list. Merger `other` (including cash plus CVR) and insurance `other`
  (including marine or travel) remain substantive options.
- Unanswered questions are recorded. Invalid probability types, nonfinite values
  and probabilities outside zero to one are unusable. A refused class question
  parks; an unanswered fit uses the class's unusable-subclass policy.
- Correspondence markers use their declared priority. An unanswered marker that
  could precede the selected subtype makes the subclass unusable. The default
  email requires answered negative markers throughout. A positive marker makes
  later refusals irrelevant. `park` sends an unusable subclass to human review;
  `keep_sorter` retains only a same-class sorter subtype, otherwise leaves it
  unresolved with no subclass confidence.
- Refused questions for unselected classes do not alter routing.
- Inside a run, the provider session ID is `sandbox-<run_id>`. Outside a run,
  no session ID is supplied. No live request verified grouping or refusal shape.

## Reproducibility limits

`apply_v42_rules()` runs after `apply_question_set_contract()`. The SHF-009
function and fingerprint remain unchanged, preserving existing locks. Golden
request-body tests cover every previously published reviewer set through 4.1.0.

The question-set SHA-256 identifies YAML bytes only. It does **not** fingerprint
`apply_v42_rules()` or prevent resume after that Python implementation changes.
An unchanged YAML digest is therefore insufficient proof of routing identity.
Before live adoption, add and verify an enforced routing-code identity in run
locks and resume checks, without rewriting published SHF-009 fingerprints or
existing experiment locks. Until that guard and the acceptance work below are
complete, keep 4.2.0 draft and out of live campaign configurations.

## Acceptance before adoption

1. Implement and test the routing identity guard described above.
2. Reserve and lock fitting and reporting calibration halves before probing.
   Probe only fitting documents. Verify actual request shape, refusal records
   and session behavior in a separately authorized, capped smoke run.
3. Select questions, compare the separate fit question with an in-question
   option, and fit thresholds using only the fitting half. All thresholds in
   this draft are provisional.
4. Freeze the chosen configuration before evaluating the untouched reporting
   half. Use the same documents for comparisons and report class and length
   support, uncertainty, human routing and measured billed cost.
5. Preserve the campaign's development and held-out boundaries, frozen analysis,
   multiplicity adjustments and operator gates. Offline tests do not establish
   model quality, production rates or live acceptance.

## Offline verification

Run with the checkout's `src` first on `PYTHONPATH`, using the intended project
interpreter and no loaded dotenv:

```bash
python -m pytest -q -n 0 --no-cov tests/test_decision_qset_v42.py tests/test_decisions_backend.py tests/test_rb1_form_controls.py
```

These tests substitute the Decisions transport. They cover request compatibility,
class-specific fit lists, form/refusal routing, marker priority and invalid
answers. Full tests, notebooks, generated checks and the unchanged 84% combined
coverage gate remain required on the current PR head in CircleCI.
