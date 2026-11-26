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
  documents were labeled. The examples come from the `calibration` and `pool` sets only, using
  near-gold and interim labels, and those sets are never used for testing.
- **Cost-effective models.** `qwen/qwen3.7-plus` judges most documents. Mergers, which are huge,
  go to the cheaper pinned `deepseek/deepseek-v4.1-flash-1017`. The document goes first in the
  prompt, so a second ruling reuses the provider's cache at a fraction of the price.
- **Staged test.** A free offline proof first, then a small paid pilot, then the full comparison.
  Each stage must pass before the next one is paid for.
- **Off by default.** Nothing changes for any existing run. Production turns it on only after the
  test shows it works.
- **Where.** Built as a sandbox patch (the repo's approved way to change the pipeline without
  editing `vendor/`). Issues for the permanent `llm-mailroom` fix are written at the end.

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
  models_by_class:
    merger_agreement: deepseek/deepseek-v4.1-flash-1017
  references: train_pool     # off | train_pool | catalog
  reference_pool: config/judge/reference-pool-runbook-v2.jsonl
```

The setting is saved in the run's lock file, so a run cannot change behaviour halfway through.
Preflight refuses the run if:

- any judge model (default or per class) has no price or no provider pin;
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
- Examples come only from the runbook-v2 `calibration` and `pool` sets (owner decision). Preflight
  refuses `train_pool` on any run that tests on those sets.
- Labels come from the near-gold catalog (`data/labels/gold/`) and the interim labels
  (`data/labels/interim/`) that count as truth. Interim labels marked `disputed` are left out.
- Documents with usable labels in those sets:

  | Type | Near-gold | Interim | Combined |
  |---|---|---|---|
  | Contract | 25 | 8 | 32 |
  | Corporate record | 112 | 54 | 118 |
  | Correspondence | 550 | 447 | 550 |
  | Insurance claim | 0 | 322 | 322 |
  | Merger | 0 | 4 | 4 |

- Where the two sources disagree on a field, near-gold wins. The pool is rebuilt and re-hashed
  whenever either source changes.

### The models, balanced for cost

Most judge cost comes from reading the document, so the design spends on a strong model where
documents are short and saves where they are huge:

| Documents | Judge model | Cost per ruling (approx.) |
|---|---|---|
| All except mergers (about 76k tokens on average) | `qwen/qwen3.7-plus` | about $0.03 |
| Mergers (about 570k tokens) | `deepseek/deepseek-v4.1-flash-1017` | about $0.17 |

Putting Plus on mergers would cost about $0.55 per ruling, so mergers go to the cheaper model.
Other ways the design keeps cost down:

- **One call per ruling.** Today a "complete" verdict takes two calls; the new judge takes one.
- **Caching.** The document goes first in the prompt, so a second ruling on the same document can
  be billed at the provider's cache price: about 20% of the input price for Plus, and about 2% for
  DeepSeek. Caching depends on the provider, so the pilot measures the cached tokens. The spend caps
  assume no caching, so they stay safe either way.
- **Retries only re-read the named fields.** There are no whole-document rounds.
- **The second ruling is rare.** It only happens after a retry the judge asked for.

Both models need a provider pin and a passing smoke test before any paid run. DeepSeek 4.1 Flash
is already pinned.

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

## The test, in stages

The earlier plan ran four full versions. This one spends money only after each cheaper stage
passes, and every version keeps today's tightened loop limits (`judge_max_passes: 2`,
`arbiter_retry_max: 1`). All versions copy the production setup and run on the same documents.

| Stage | What runs | Cost | Must pass before the next stage |
|---|---|---|---|
| 0. Offline proof | the pipeline with fake model answers | free | every path ends within two rulings and one retry; call counts per path match the design |
| 1. Pilot | `dev-look1` (302 documents): today's judge vs the new judge with examples, plus the new judge without examples | small | the new judge makes at least 50% fewer judge-related calls; no extra crashes; cost per judged document no higher than today |
| 2. Full test | `dev` (900 documents): today's judge vs the new judge with examples | larger | the success rules below |

The "without examples" version runs only in the pilot, to show cheaply what the examples add. The
earlier "today's judge on the stronger model" version is dropped to save cost.

**Success (full test):**

- at least 50% fewer judge-related calls per judged document;
- judge cost per judged document no higher than today, by document type;
- on judged documents, an extraction score at most 2 points below today, with a paired bootstrap
  interval (owner decision);
- no more wrong archives;
- no leaks.

Each paid stage needs a person's initials at the spend gate. Its spend cap is worked out from the
per-ruling costs above with the repo's 1.5x margin.

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
5. **Extra information.** Earlier attempts and guide definitions. The reference pool builder reads
   near-gold and interim labels for `calibration` and `pool`, with its leak checks.
6. **Reports.** Before and after scores, fix accuracy, calls, cost and rulings in the gate and
   routing reports.
7. **Models and tests.** Add the provider pin for `qwen/qwen3.7-plus`, the per-class judge model,
   and the document-first prompt order for caching. Write the stage 1 and stage 2 configs and their
   spend caps.
8. **Hand over.** Open a PR, draft the upstream issues, and hand each paid stage to you to launch.

## Decisions made by the owner (2026-11-26)

1. Examples come from the `calibration` and `pool` sets, using near-gold and interim labels.
2. The judge takes the most cost-effective route without losing effectiveness. The per-class
   models, caching and the staged test above are the design's answer.
3. Score margin: at most 2 points below today on judged documents, tested on the full `dev` set.
4. The test design is reworked to cut repeat judge and arbiter loops and wasted calls.

## Calls I made

- Examples from the full label catalog are refused on scored runs.
- The new judge works with OpenRouter only.
- Fixes cannot blank fields. A document with an unfixed wrong field cannot be archived.
- A retry the judge asks for always comes back to the judge (except matter conflicts).
- "Before the judge" means the extraction the judge first saw.
- Examples are matched by type and subtype, at most two. Where near-gold and interim labels
  disagree, near-gold wins.
- Judge models: `qwen/qwen3.7-plus` by default, `deepseek/deepseek-v4.1-flash-1017` for mergers.
- The test runs in three stages; the "model only" version is dropped.

## Left to the builder

- The judge's prompt wording.
- Size limits for earlier attempts and examples.
- The pool builder's name and file format.
- The test file layout.
