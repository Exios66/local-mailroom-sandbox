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
- **Loop governor.** A new per-document governor caps all retries, model calls and spend across the
  whole pipeline (classify retries, extraction retries, arbiter, boss), not just the judge. When a
  document runs out, the governor sends it to a clear outcome instead of another round, so a runaway
  document ends as a scored review, not a crash or an endless loop.
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
- The classification judge's and the boss's own logic, scoring rules and labels. (The governor
  limits how often retries and the boss can run, but does not change what they decide.)
- The existing hard call ceiling stays as the last-resort backstop; the governor acts before it.
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

### The loop governor (whole pipeline)

**The problem it fixes.** Each loop has its own limit today: `retry_max`, `arbiter_retry_max`,
`judge_max_passes`, `transient_retry_max` and the classify retries. Nothing limits them together, so
one document can stack them. The only overall stop is the hard call ceiling (40 calls for a pipeline
document, `job/call_guard.py`). When it trips, the document crashes and drops out of the scores.

**The governor** keeps one budget per document, counted across every node:

| Budget | Counts | Default (my call; the pilot sets the final values) |
|---|---|---|
| Retries | classify retries, extraction retries, judge-requested retries, arbiter retries, boss entries | 2 per document |
| Model calls | every LLM call for the document | 30 (below the hard ceiling of 40); mergers 36 |
| Spend | priced calls for the document, using the live call guard | off until the pilot measures cost per type |

Transient provider errors keep their own small limit (`transient_retry_max: 1`) and also count
toward the call and spend budgets.

**When a budget runs out,** the governor checks before each step that would add a round (a retry, an
arbiter call, a second ruling, a boss entry) and routes the document to one of these outcomes
instead:

| Outcome | When | Result |
|---|---|---|
| `archive_with_caveats` | the current extraction already passed the judge or the fix checks | archived, marked `governor_stop`, scored |
| `human_review: retry_budget` | the retry budget is spent | sent to a person, scored as review |
| `human_review: call_budget` | the call budget is spent | sent to a person, scored as review |
| `human_review: spend_budget` | the spend budget is spent | sent to a person, scored as review |
| `human_review: boss_repeat` | a second boss entry is requested | sent to a person, scored as review |

The hard ceiling stays as a backstop, so a crash now means the governor has a bug. Every stop is
recorded on the result (`governor_stop`: reason, node, calls, retries and spend so far).

**How it is built.** The governor is part of the same sandbox patch. It uses routing rules on the
pipeline's existing routers (the method the repo's earlier routing fixes use), plus the call
guard's per-document counters. It is switched on by `job.governor` in the run config, which is saved
in the lock. It is off for existing runs and on in every new test version and, after the test, in
production. It works with or without the new judge.

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
| Governor stops by reason and type; crashes | shows runaway documents now end cleanly |

Scores that include judge fixes are labelled "after judge". Judge-corrected documents are counted,
and stay in every total.

## The test, in stages

The earlier plan ran four full versions. This one spends money only after each cheaper stage
passes, and every version keeps today's tightened loop limits (`judge_max_passes: 2`,
`arbiter_retry_max: 1`). All versions copy the production setup and run on the same documents.

| Stage | What runs | Cost | Must pass before the next stage |
|---|---|---|---|
| 0. Offline proof | the pipeline with fake model answers | free | every path ends within two rulings and one retry; every governor outcome is reached and ends cleanly; call counts per path match the design |
| 1. Pilot | `dev-look1` (302 documents): today's judge with the governor off and on, the new judge with examples, and the new judge without examples | small | the new judge makes at least 50% fewer judge-related calls; no extra crashes; cost per judged document no higher than today |
| 2. Full test | `dev` (900 documents): today's judge vs the new judge with examples | larger | the success rules below |

The "without examples" version runs only in the pilot, to show cheaply what the examples add. The
earlier "today's judge on the stronger model" version is dropped to save cost. Every version runs
with the governor on, including today's judge, so loop savings from the governor and from the new
judge can be told apart. The pilot also adds "today's judge, governor off" as the plain baseline,
and its call counts per document type set the governor's final budgets.

**Success (full test):**

- at least 50% fewer judge-related calls per judged document;
- judge cost per judged document no higher than today, by document type;
- on judged documents, an extraction score at most 2 points below today, with a paired bootstrap
  interval (owner decision);
- no more wrong archives;
- no crashes from the hard call ceiling;
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
5. **Loop governor.** The `job.governor` switch, the per-document retry, call and spend budgets,
   the routing outcomes, and the `governor_stop` record. Offline tests reach every outcome.
6. **Extra information.** Earlier attempts and guide definitions. The reference pool builder reads
   near-gold and interim labels for `calibration` and `pool`, with its leak checks.
7. **Reports.** Before and after scores, fix accuracy, calls, cost, rulings and governor stops in
   the gate and routing reports.
8. **Models and tests.** Add the provider pin for `qwen/qwen3.7-plus`, the per-class judge model,
   and the document-first prompt order for caching. Write the stage 1 and stage 2 configs and their
   spend caps.
9. **Hand over.** Open a PR, draft the upstream issues, and hand each paid stage to you to launch.

## Decisions made by the owner (2026-11-26)

1. Examples come from the `calibration` and `pool` sets, using near-gold and interim labels.
2. The judge takes the most cost-effective route without losing effectiveness. The per-class
   models, caching and the staged test above are the design's answer.
3. Score margin: at most 2 points below today on judged documents, tested on the full `dev` set.
4. The test design is reworked to cut repeat judge and arbiter loops and wasted calls.
5. A governor on the whole pipeline's retries, with clear routing outcomes, to stop excess spend
   loops.

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
- Governor starting budgets: 2 retries, 30 calls (mergers 36), spend off until measured. The pilot
  sets the final values. The governor is off for existing runs and on for every new test version.
- A document whose current extraction already passed the checks is archived with caveats when the
  governor stops it; every other stop goes to human review.

## Left to the builder

- The judge's prompt wording.
- Size limits for earlier attempts and examples.
- The pool builder's name and file format.
- The test file layout.
