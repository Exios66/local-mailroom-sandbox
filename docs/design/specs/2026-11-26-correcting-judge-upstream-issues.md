# Correcting judge: upstream issue drafts for `llm-mailroom`

Companion to the [correcting-judge design](2026-11-26-correcting-judge-design.md) ("Rolling it out").
These are five drafts for the owner to file against `llm-mailroom`. Each one names the sandbox hotfix that
stands in for it today. A hotfix is retired, and its row removed from
[`docs/vendor-hotfixes.md`](../../vendor-hotfixes.md), only once upstream ships every behaviour it carries and
the vendor snapshot is refreshed (`/vendor-sync`). HF-018 backs both draft 4 (call limits) and draft 5 (the
Boss-repeat stop): when only one ships, revalidate it and keep the remaining behaviour until the other ships too. Label-assisted routing (`llm-mailroom` #207) is already filed and is not
repeated here.

The drafts follow the repository's PR and issue rule: an executive summary, with no transcript, names or
credentials.

---

## 1. A judge that corrects fields, with quotes

**Summary.** When the completeness judge finds a weak field, it can only send the whole document back for
another extraction or to the arbiter. Let it propose a fix for each weak field instead: the field, the value
and an exact quote from the document. The pipeline applies a fix only after a deterministic check passes: the
field was asked about, the value is not blank, the quote is found in the document, and the quoted text supports
the value.

**Why.** Today a judged document costs up to two judge passes, an arbiter call and a full re-extraction, and the
last attempt wins even when it is worse. Most weak fields are a single value the judge can already see in the
text.

**Proposed change.**

- Add a ruling schema: `accept` (with fixes), `retry_fields` (naming fields) or `human_review`, plus
  `wrong_fields`.
- Add a fix check that calls no model: requested field, not blank, quote located, value supported.
- Safety rules: an accept with an unfixed wrong field becomes a retry on the first ruling and a person on the
  second; a fix can never erase a field.

**Sandbox stand-in.** HF-025 (`judge_verify_node`), with `mailroom_sandbox.correcting_judge` and
`mailroom_sandbox.judge_fixes`.

**Done when.** A judged document's verified fixes are written to its result and every ruling is recorded. An
unverified fix never changes a field.

---

## 2. A direct judge-to-retry route for named fields

**Summary.** When the judge asks for a retry, re-extract only the fields it named, keep every other field, and
return to the judge for one final ruling. The arbiter is not called after a correcting ruling.

**Why.** A full re-extraction re-reads the whole document, can lose fields that were right, and often goes
through the arbiter first. A field-only retry asks for less and cannot damage the rest of the extraction.

**Proposed change.**

- The retry node accepts a field list and sends the specialist a schema restricted to those fields, keeping
  `confidence` and `reasoning`.
- Merge the reply into the previous extraction field by field: unnamed extraction fields are kept, and the
  re-read's own metadata (confidence, reasoning, guardrail marks) is the fresh one.
- Route a reviewable retry back to the judge. A second ruling can never retry, so every document ends within two
  rulings and one retry. A re-read that failed (unparseable, guardrail-failed, unsupported or schema-invalid)
  goes to a person without a second ruling; a transient-error loop and a Boss conflict keep today's route.
- Skip the arbiter's model call when the judge's ruling is final.

**Sandbox stand-in.** HF-027 (`retry_extract_node`, wrapping `_enrich_contract_result`, with a route rule on
`after_retry_extraction_gated`) and HF-026 (`arbiter_node`).

**Done when.** A retry request carries only the named fields, the other extraction fields are unchanged after the
merge, a failed re-read reaches a person without a second ruling, and no path makes more than two rulings.

---

## 3. Export a document's earlier attempts

**Summary.** Make a document's earlier extraction attempts, with their judge verdicts and findings, available to
the judge prompt and in the result, bounded in size.

**Why.** A judge that sees only the latest attempt cannot tell a value that changed between attempts from one
that held steady, and it repeats findings it already made. Reports cannot show what the judge changed without
the extraction from before the judge.

**Proposed change.**

- Expose the attempt history (attempt number, kind, fields without internal keys, verdict and findings) as a
  supported state key.
- Let the judge prompt include the attempts before the one under review, newest first, within a character
  budget.
- Record the extraction from before the judge in the result.

**Sandbox stand-in.** `mailroom_sandbox.judge_references.attempts_for` reads `extraction_attempt_history`, and
HF-025 records `before_judge` through `mailroom_sandbox.judge_record`.

**Done when.** The judge prompt holds bounded earlier attempts, and the result carries the extraction from
before the judge.

---

## 4. A per-document call limit that ends in review, not a crash

**Summary.** Give each document one budget across every node (rounds, model calls and optionally spend). When
the budget runs out, the document stops at a recorded outcome: human review, or archive with caveats when its
latest attempt was judged complete and the archive guards hold. Today the hard call ceiling raises an error and
the document crashes.

**Why.** A document that loops (extract, judge, arbiter, retry) runs until the ceiling refuses it, so it is
billed for every call and then reported as a crash instead of a review.

**Proposed change.**

- Check a per-document budget before each step that would add a round.
- Stop at review, or at archive with caveats under the vendored archive guards, and record the reason, the node
  and the counts.
- Count every HTTP attempt, a failed one included, toward the budget, with one retry layer.

**Sandbox stand-in.** HF-018 (`graph.route_spec.decide_route`) and `mailroom_sandbox.governor`, from Phase 2
(`job.governor`).

**Done when.** No document crashes on the call ceiling, and every stop records its reason.

---

## 5. Boss loops

**Summary.** A document can enter the boss (matter-conflict) step more than once, and re-ingested or
near-duplicate copies of archived documents escalate to the boss on every pass. Stop a second boss entry at
human review, and link exact and near copies as duplicates before the conflict check, with no boss call.

**Why.** Repeated boss entries are the most expensive loop in the pipeline, and duplicate re-scans of one matter
are the commonest trigger.

**Proposed change.**

- Allow one boss entry per document, and route a second one to review with the reason recorded.
- Before the conflict check, link an exact copy, or a near copy whose differing archived values all appear in
  its own text, as `duplicate_of`.
- Escalate a near copy whose differing values are not in its text to the boss as today.

**Sandbox stand-in.** HF-018 (`boss_repeat`) and HF-019 (`graph.build_graph._detect_conflict`), from Phase 2.

**Done when.** No document enters the boss twice, and an exact re-ingestion makes no boss call.
