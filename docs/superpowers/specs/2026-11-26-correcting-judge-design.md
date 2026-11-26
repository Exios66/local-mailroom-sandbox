# Correcting judge — design

Status: draft for owner review · approach chosen by the owner: build in the sandbox first, fix
`llm-mailroom` later · 2026-11-26

## Executive summary

- **Problem.** When the pipeline is unsure about an extraction, the judge only says "complete",
  "partial" or "incomplete". Another agent (the arbiter) then decides what to do, and a retry
  re-reads the whole document. Documents stuck in this loop cost about 40 extraction calls each,
  against about 14 for a document that skips it.
- **Change.** The judge makes the final call itself, in one step: accept the extraction (fixing
  wrong fields), retry only the named fields once, or send the document to a person. Every fix must
  quote the source document, and code checks the quote before the fix is used.
- **Limit.** At most two judge rulings and one retry per document. A document that reaches the limit
  goes to human review, so it stays in the scored results.
- **Better information.** The judge also sees earlier attempts, the labeling guide, and how similar
  documents were labeled, drawn only from documents that are never used for testing.
- **Stronger model.** The judge moves to `qwen/qwen3.7-plus`, pinned to one provider.
- **Off by default.** Nothing changes for any existing run. Production turns it on only after a
  test shows it works.
- **Where.** Built as a sandbox patch (the repo's approved way to change the pipeline without
  editing `vendor/`). Issues for the permanent `llm-mailroom` fix are written at the end.
- **Decisions needed from you.** Where reference labels come from, the cost per judged document,
  and the acceptable score margin (see the end).

## The problem

- The judge only diagnoses. Fixing is left to a full retry, then the judge runs again.
- The judge sees only the document and the extracted fields. It does not see earlier attempts, the
  labeling guide, or how similar documents were labeled.
- Measured cost: about 40 extraction calls per looping document
  (`docs/audits/2026-11-15-pipeline-qwen-flash-25-failure-modes.md`), and merger documents running
  about 140 calls in the R01 smoke test.

## What will change

1. A new optional `judge:` section in run configs switches the new judge on.
2. The judge returns one ruling: **accept**, **retry these fields**, or **human review**.
3. The judge can fix fields. Each fix gives the new value and a quote from the document.
4. Code checks every fix: the field must exist, the quote must appear in the document, and the
   value must match the quote. Failed fixes are recorded and not used.
5. The arbiter makes no model call when the new judge is on. It just passes the judge's ruling on.
6. A retry re-reads only the fields the judge named. All other fields are kept.
7. Each result records the judge's ruling, its fixes, and the extraction before the judge, so the
   judge's effect can be measured.

## What will not change

- Which documents reach the judge.
- The classification judge, the boss, the global call limit, scoring rules and labels.
- Any run without the `judge:` section, including all past runs.

## How it works

### The switch

```yaml
judge:
  mode: correct              # "verify" = today's behaviour
  model: qwen/qwen3.7-plus
  references: train_pool     # off | train_pool | catalog
  reference_pool: config/judge/reference-pool-runbook-v2.jsonl
```

The setting is saved in the run's lock file, so a run cannot change behaviour halfway through.
Preflight refuses the run if:

- the model has no price or no provider pin;
- the reference pool file is missing or changed;
- any tested document is in the reference pool, or shares a thread, matter or text with it;
- `catalog` references are used on a run that is scored (they are only for unlabeled real mail).

### The ruling

- **Accept.** Verified fixes are applied and the document is archived, marked "judge corrected".
- **Retry these fields.** One re-read; only the named fields are replaced; then the judge rules a
  second and final time. The second ruling cannot ask for another retry.
- **Human review.** The document goes to a person with the judge's reason.
- **Safety rules.**
  - A fix can never blank a field.
  - If the judge says a field is wrong but has no verified fix for it, the document cannot be
    archived: it is retried on the first ruling, or sent to a person on the second.
- **Matter conflicts.** These still go to the boss, as today. Each one is counted.

### What the judge reads

- the whole document (as today);
- the extracted fields and the earlier attempts;
- the labeling guide's definitions for that document type;
- up to two labeled examples of the same type and subtype.

### References without cheating

- The judge must never see labels for the document it is judging, or for any test document.
- In tests, examples come only from split sets that are never tested. Which sets is decision 1.
- Contracts and corporate records only have labels outside the test sets in `calibration`
  (25 contracts, 112 corporate records).
- Insurance claims and mergers have no labels, so they get no examples.

### The model

`qwen/qwen3.7-plus` reads whole documents (1M-token context). It costs about 10 times the current
judge. A whole merger costs about $0.55 per ruling. It needs a provider pin and a passing smoke test
before any paid run.

## How we will measure it

| Measure | Why |
|---|---|
| Final extraction score (as today) | the headline number, unchanged |
| Score before the judge, on judged documents | shows what the judge added |
| Fixes proposed, verified, and right or wrong | shows whether fixes can be trusted |
| Rulings and retries per judged document | shows the loop is gone |
| Model calls and cost per document | shows the saving |
| Review rate and wrong-archive rate | shows nothing got worse |

Scores that include judge fixes are labelled "after judge". Judge-corrected documents are counted,
and stay in every total.

## The test

Four versions of the production setup, on the same documents:

1. today's judge;
2. today's judge on the stronger model;
3. new judge, stronger model, no examples;
4. new judge, stronger model, with examples.

This separates the effect of the model, the new behaviour and the examples. Each version runs free
(mock) first. Paid runs need a person's initials at the spend gate.

**Success:**

- at least 50% fewer judge-related calls per judged document;
- an extraction score no worse than today, within the agreed margin;
- no more wrong archives;
- no leaks.

## Rolling it out

- **Production.** One reviewed change adds the `judge:` section to the production configs and their
  tests. The Modal production worker is redeployed with the patch.
- **Upstream.** Issues for `llm-mailroom`:
  1. a judge that fixes fields with quotes;
  2. a direct judge-to-retry route for named fields;
  3. export earlier attempts;
  4. a per-document call limit that ends in review, not a crash;
  5. boss loops.

  The sandbox patch is removed once upstream ships.

## Safety rules

- No edits to `vendor/`.
- No paid runs by an agent.
- Every paid run has a spend cap and a time limit.
- Adding the patch stops old unfinished runs from resuming without `--force`. Finished runs are
  unaffected.
- The PR checks every relevant item in `docs/critical-regressions.md` (rows 1, 3, 5, 6, 9, 12, 14,
  15, 17 and 22).

## Plan

Each step is its own commit with tests. The full test suite runs in CircleCI.

1. **Switch.** Add the `judge:` config section, the lock entry and the preflight refusals. Existing
   configs are unchanged.
2. **Record.** Save the judge's ruling, fixes and the before-judge extraction on each result, for
   both the old and the new judge.
3. **Fix checking.** Verify quotes and values with the existing label tools (`gold_labels.locate`,
   `evidence_support`).
4. **New judge.** The sandbox patch: the one-step ruling, the arbiter pass-through, the field-only
   retry, and the two-ruling limit. Tests on the offline pipeline prove every path ends.
5. **Extra information.** Earlier attempts, guide definitions, and the reference pool builder with
   its leak checks.
6. **Reports.** Before and after scores, fix accuracy, calls, cost and rulings in the gate and
   routing reports.
7. **Model.** Add the provider pin for `qwen/qwen3.7-plus`. Write the four test configs and their
   spend caps.
8. **Hand over.** Open a PR, draft the upstream issues, and hand the paid test to you to launch.

## Decisions needed from you

1. **Where reference examples come from.** Recommended: the `calibration` and `pool` sets, with
   runs that test on those sets refused. Alternatives: label more contracts first, or use examples
   for correspondence only for now.
2. **Cost.** About $0.55 per merger ruling would exceed today's production caps ($2 per 100
   documents). Options: raise the caps; use a cheaper judge for mergers only; or limit how much of a
   merger the judge reads.
3. **Score margin.** Proposed: the new judge may score at most 2 points lower than today on judged
   documents, tested on the full `dev` set (900 documents) for enough data.

## Calls I made

- Examples from the full label catalog are refused on scored runs.
- The new judge works with OpenRouter only.
- Fixes cannot blank fields. A document with an unfixed wrong field cannot be archived.
- A retry the judge asks for always comes back to the judge (except matter conflicts).
- "Before the judge" means the extraction the judge first saw.
- Examples are matched by type and subtype, at most two.
- The judge model is `qwen/qwen3.7-plus`.

## Left to the builder

- The judge's prompt wording.
- Size limits for earlier attempts and examples.
- The pool builder's name and file format.
- The test file layout.
