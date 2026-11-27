# Phase 5 part 2: better merger extraction with fewer whole-document reads

Status: design, for owner approval. Builds on
[the correcting-judge design](2026-11-26-correcting-judge-design.md) (Phase 5, D1/D2) and
[Phase 5 part 1](2026-11-27-phase5-attempt-hygiene-design.md), re-scoped to the OpenRouter production
route (`qwen/qwen3.7-flash`, 1M context, one-call whole-document reads).

## Why

Merger agreements are the weakest, longest and most expensive class on the production route:

- **Quality.** The merger headline is MAUD accuracy alone (`eval/scoring.py:329`), and it sits at
  0.09 to 0.11 in every run so far: the E3 control (0.106), SAND-214 with the tuned `maud_v2` prompt
  (0.091) and the Qwen-25 audit (7 of 79 answers).
- **Length.** The median merger is about 340k characters (about 85k tokens); 151 of 152 are over
  150k characters.
- **Cost.** About 74% of a mixed run's tokens, because the whole agreement is read again and again.
  The autoresearch `mailroom-v1` run recorded per-step usage for 5 whole-document mergers: about 590k
  prompt tokens each, about 7.6 whole-document reads.

| Step (mailroom-v1, 5 mergers) | Calls per doc | Prompt tokens per doc | Share |
|---|---|---|---|
| judge | 3.0 | 233k | 39% |
| merger specialist | 1.8 | 138k | 23% |
| sorter | 1.0 | 80k | 13% |
| intake | 1.0 | 77k | 13% |
| arbiter | 0.8 | 61k | 10% |

The judge and arbiter, half the tokens, have not improved a merger result: the Qwen-25 audit found
the judge passed 0 of 8 mergers, and 0 of 4 retries improved a verdict.

The likely cause of the low score is the read itself. One call is asked 22 detailed legal questions,
each with a fixed answer list of 2 to 95 classes, about an 85k-token agreement, at the same time as 16
entity fields. Chunking does not help MAUD: each question has one answer, so chunks return competing
answers (9 conflicts on one 14-window Qwen-25 read; SAND-214's chunked reads averaged 0.091).

## What the owner decided

- **Raise MAUD accuracy and cut whole-document reads.** Every read of an 85k-token agreement is token
  burn, so the design minimises them. Confirmation needs a paid run, which the owner launches.
- **Approach B with section reads (option 1), plus head reads for long documents (option 3), as
  separate switches.**
  - **Option 1.** One whole-document extraction read. The MAUD question-group reads and the retry read
    only the sections they need. Mergers skip the judge loop.
  - **Option 3.** The sorter and intake read only the opening of very long documents.
- **Use the designated merger schema**, the Dojo's `MergerAgreementExtraction`
  (`maud_schema.py`, schema id `merger_agreement@v9.3`, 21 fields). Capture **only the fields valid
  for the document's subclass**.
- **Retries target only what the first round did not cover or got wrong**, never the whole extraction.
- **Add an entity-field check for mergers**, reported next to MAUD, not in the headline.
- **Labels for the entity check.** Near-gold labels now, made the repo's way (two agreeing passes or
  an Opus review), plus a human spot-check of a sample before anyone cites the numbers.

## Goals, non-goals and anti-goals

Goals:

1. **Fewer reads.** About 2 whole-document reads per merger, down from 5 to 7, measured per step.
2. **Better MAUD.** A higher paired MAUD accuracy on the stage-1 mergers.
3. **Subclass fields.** Each merger subclass is asked only for its valid fields, from the Dojo's own
   definitions.
4. **Targeted retries.** A retry re-asks only the missing or invalid items, reads only their sections,
   and changes nothing else.
5. **Entity accuracy.** A measured entity-field accuracy for mergers, with its label source and n
   stated.

Non-goals:

- Other classes' extraction. Long contracts and corporate records are touched only by the head-read
  switch (part 5), and only their sorter and intake reads.
- Changing the merger headline (it stays MAUD accuracy) or any scorer. Dojo owns scoring.
- New prompt versions. Frozen prompts stay frozen; any added instruction is generated deterministic
  text, as the subclass field note does (`docs/design/plans/2026-11-27-subclass-field-note.md`).

Anti-goals (a failure even if the code works):

- Entity fields get worse because MAUD moved to other reads.
- A wrong sorter subclass silently drops a field the document has.
- A section locator miss quietly turns into another whole-document read.
- The head-read cap makes any class, or the merger subclass, classify worse.
- A replay, mock or estimate is cited as a quality result.
- The stage-1 baseline changes behaviour. Everything here is off unless a run sets it.

## Constraints

- Offline build: no paid or live work from an agent. The owner runs the stage-1 baseline and the
  confirming arms with their own initials.
- `vendor/` is never edited. Pipeline changes are sandbox hotfixes (next free IDs: HF-030 to HF-032;
  reserve them in `docs/numbering-reservations.md`), each with a pinned source and a
  `docs/vendor-hotfixes.md` row.
- Mesh with open PRs; touch nothing on #425, #430, #437 or #439. The rc.10 labels on #425 are read only.
- A run scored with `dataset.staged_overlay` cannot also merge interim or near-gold labels
  (`job/spec.py:184`). The stage-1 runs use rc.10, so the entity check cannot ride on the run's truth.
- HF-010 makes an API-routed sorter or intake fail (`WholeDocumentTooLong`) rather than split a document
  into windows. The head-read switch must replace that failure with a head read, never with windows.
- Every new switch is a `StrictBool`, pipeline runs only (the head-read switch also for `task: sorter`),
  hashed into `spec_hash` only when set (the `job.evidence_check` pattern), so existing locks and the
  baseline's hash are unchanged.
- Sealed held-out documents are never read to build anything committed.
- Coverage floor 84; local tests are named files with `-n 0 --no-cov`.

## Approaches considered

| | Approach | Trade-off | Verdict |
|---|---|---|---|
| A | Chunked read with the evidence merge (E1's 1.8× read) | Proven for contract clause lists, where each chunk adds items. MAUD answers are one-per-question, so chunks conflict; past chunked merger reads scored 0.09 to 0.10 | Rejected |
| B-whole | One whole-document read per MAUD question group | No conflicts, but 4 whole-document reads: more token burn, not less | Rejected by the owner |
| **B-sections** | **One whole-document extraction read; MAUD question groups and the retry read only their located sections; no judge loop** | About 1 whole read plus small excerpts. Depends on a deterministic section locator | **Chosen (option 1)** |
| B-all-sections | As B-sections, with the entity fields also read from sections | About one read fewer, but the entity fields depend on the locator | Not chosen: it risks the entity fields the owner wants improved |
| **Head reads** | **Sorter and intake read only the opening of very long documents** | Removes most of the two remaining whole reads; affects every long document's classification read | **Chosen (option 3), its own switch** |
| C | Locate clauses, then answer from the quotes | Cheapest, but clause finding by the model is unproven | Fallback if MAUD does not move |

## The design

Four switches, all off by default, so the confirming arms can attribute each gain:

```yaml
job:
  merger:
    subclass_fields: true    # only the fields valid for the subclass (part 1)
    question_groups: true    # MAUD question groups read from their sections (part 2)
    gap_retry: true          # one targeted retry, from sections (part 3)
  long_document_head: true   # sorter and intake read the opening of very long documents (part 5)
```

- `question_groups` and `gap_retry` require `subclass_fields` (they use its field set).
- The three merger switches apply only to documents routed to `merger_agreement_specialist` on a
  one-call read. A chunked read (Modal or local routes) keeps today's behaviour, and preflight says so.
- `long_document_head` is independent of the other three.

### 1. Subclass fields (`job.merger.subclass_fields`)

Today every merger subclass is sent the class schema minus `intent`, `keywords` and `subject_matter`
(`config/extraction/subclass_extraction_fields.json`). The Dojo says which consideration fields apply
to each subclass (`maud_schema.ConsiderationSubclass.entity_hints`):

| Subclass | Consideration fields that apply | Dropped under this switch |
|---|---|---|
| `all_cash` | `per_share_cash_amount` | `exchange_ratio` |
| `all_stock` | `exchange_ratio` | `per_share_cash_amount` |
| `mixed_cash_stock`, `mixed_cash_stock_election` | both | none |
| `other` | neither named | none (kept: "other" can be anything) |

The rule is generated, never hand-listed: of the two consideration-amount fields, keep those the
subclass's entity hints name, and when it names neither, keep both.

- Derive it in `scripts/build_subclass_fields.py` as a separate, switch-gated section of the committed
  field lists. `--check` keeps it fresh, and the default lists (and so the baseline) stay byte-identical.
- The subclass's priority questions (`ConsiderationSubclass.priority_questions`) set the question order
  in part 2. Every MAUD question stays valid for every subclass (the Dojo marks none invalid).
- Hint fields that are not in the schema are not added: `cvr`, `cash_in_lieu_of_fractional_shares`,
  `election_mechanics`, `proration` and `consideration_description`. They would be unscored, and the
  owner asked to capture only valid schema fields. (My call; easy to revisit.)

**A wrong subclass must not lose a field.** This protection belongs to this switch, so it holds even
when `gap_retry` is off (an ablation arm may run `subclass_fields` alone):

- The existing low-confidence fallback stays: when the sorter's subclass confidence is too low,
  `subclass_extraction.choose_schema` sends the full class schema, and nothing is dropped.
- The main read still extracts `merger_consideration`. When its token disagrees with the sorter's
  subclass (using the Dojo's `equivalent_to`), the field the sorter's subclass dropped is asked in one
  small call, from its section (part 2's locator: the Article II share-conversion section).
- With `gap_retry` on, that field is folded into the single gap-retry call (part 3) instead.

### 2. Question-group reads from sections (`job.merger.question_groups`)

**The main read is unchanged.** It uses the frozen prompt, the subclass schema and the whole document,
and fills the entities, the consideration and a first answer to every MAUD question. It is the one
whole-document extraction read.

**The section locator** is deterministic, with no model call. It is a new sandbox module (e.g.
`mailroom_sandbox.merger_sections`) that finds, in the working text:

- article and section headings (`ARTICLE VI`, `Section 6.3 No Solicitation`, and the like), skipping
  the table of contents;
- defined-term paragraphs (`"Company Material Adverse Effect" means …`, up to the next defined term).

It maps each MAUD question to the sections the Dojo's own hints name (`MaudQuestion.sections`, for
example MAE Definition → the "Material Adverse Effect" definition; No-Shop → the No Solicitation
covenant). The matching rules (heading words and defined terms per question) are one committed table,
generated from those hints plus a short reviewed synonym list. An excerpt is the matched section's text
up to the next heading of the same or higher level. It is capped per question (my call: 24k characters,
cut at a paragraph boundary), and a cut is marked so the model knows.

**The groups.** Up to three group reads, each re-asking one MAUD group from its questions' excerpts
only:

| Read | MAUD questions (Dojo `group`) | Count |
|---|---|---|
| main (whole document) | all (fallback answers); its own answers stand for General Information, Knowledge, MAE and Remedies | 22 (4 owned) |
| group 1 (sections) | Deal Protection: no-shop, fiduciary outs, superior offer, intervening event, tail period, breach of no-shop | 6 |
| group 2 (sections) | Deal Protection: matching rights (COR, FTR), FTR triggers, limitations on FTR, fiduciary exception to COR, breach of meeting covenant | 6 |
| group 3 (sections) | Conditions to Closing and Operating and Efforts Covenant | 6 |

- The grouping is my call. It splits the Dojo's 12-question Deal Protection group in two, keeps each
  read at 4 to 6 questions, and leaves MAE (40 classes) with the main read.
- `job.merger.groups` (1 to 3, default 3) sets the number of group reads by merging groups into
  fewer, larger reads. Every non-main question still has one owner; nothing is dropped.
- The table is generated from the Dojo's `group` field plus one committed split list. The builder may
  rebalance it, as long as each question is owned by exactly one read.

**Each group read:**

- sends the same system prompt and handoff text as the main read, then the deduplicated excerpts for
  its questions (each labelled with its heading), then a generated instruction block from the Dojo's
  `render_maud_question_block(subclass, shape="lines", questions=<group>, chunked=False)`: the group's
  questions with every allowed answer verbatim, and "the text below is the relevant sections of the
  agreement";
- uses a response schema with only `maud_clauses`, whose items are constrained to the group's valid
  `"<Question>: <answer>"` lines (an enum built from `valid_classes`). If the provider rejects the enum,
  it falls back to the unconstrained list and validates after;
- goes through the same specialist call path, so the call guard, governor, spend cap and usage capture
  count every call. Usage is attributed to `merger_agreement_specialist`, with a `maud_group` tag so
  the cost report can split it.

**When the locator misses.** A question whose sections the locator cannot find is not sent to its
group read, and keeps the main read's answer. Its miss is recorded under `_maud_section_missed`. A
group with no located question makes no call. **A miss never becomes a whole-document read** (an
anti-goal).

**Combining.** For each question, the owning read's valid answer wins. A question its owner left
unanswered or answered invalidly falls back to the main read's valid answer, then to the gap retry.

- Answers are normalised and validated with the Dojo's `parse_maud_clause`.
- Only `maud_clauses` changes. Every entity field comes from the main read alone (the anti-goal guard).
- The merged extraction then goes through `_enrich_contract_result` like any other, so the guard,
  conflict check, attempt history and HF-029 see one extraction.
- A group read that fails (parse error, transport error after the usual transient retry, or budget
  refusal) leaves the main read's answers for its questions, records `_maud_group_failed`, and never
  fails the document.

**Offline locator check.** Before any paid run, a committed script reports, on the 34 calibration
mergers only:

- per question, the share of agreements where its section was found;
- the median and maximum excerpt size;
- the estimated tokens per group read.

The labels carry no clause text (only the answer and `excerpt_chars`), so this measures coverage and
size, not correctness. A question found on fewer than 80% of calibration agreements is listed in the
design follow-up, and its matching rules are revisited before the paid arm.

### 3. Gap retry (`job.merger.gap_retry`)

After the main read and group reads, one more call re-asks only the items that are missing or
invalid.

**How it runs.**

- It runs **inside the extraction step**, as the step's last call, not as a graph retry.
  `extraction_attempts`, `retry_max`, the attempt history and routing are unchanged.
- It reuses the HF-027 mechanism for the request and the merge: `subclass_extraction.fields_only`, then
  a merge that replaces only the named items.
- The call guard, the spend cap and the governor's call and spend budgets count it.
- For MAUD, targets are named per question, not as the whole `maud_clauses` field.

**Targets.**

1. A MAUD answer that is not one of its question's valid answers (a definite error).
2. A near-universal MAUD question left unanswered.
   - Near-universal means labelled on at least 90% of the **calibration-set** merger agreements in
     `config/splits/runbook-v2/assignments.jsonl` (34 documents).
   - Dev documents (which any look can draw) and sealed held-out documents are never read for this
     list.
   - On today's labels that gives 11 questions:
     - 100%: Accuracy of Target R&W, Fiduciary exception to COR, MAE Definition, Ordinary course
       covenant and Tail Period;
     - 97%: matching rights for COR and Negative interim operating covenant;
     - 94%: Intervening Event Definition and No-Shop;
     - 91%: Knowledge Definition and Superior Offer Definition.
   - The list is generated and committed with its source counts and split digest, and a test fails if
     it reads a non-calibration document.
3. A required entity field, valid for the subclass, that came back empty. Required means a field every
   executed merger agreement states. My call, as a committed list: `document_name`, `parties`,
   `acquirer`, `target`, `governing_law` and `outside_date`, plus the subclass's consideration-amount
   field or fields.
4. The dropped consideration field after a subclass disagreement (part 1).

**What it reads.** The gap retry reads **only sections**: the target questions' excerpts, and for
entity targets the locator's entity sections (my call, as a committed table):

| Entity target | Section read |
|---|---|
| `document_name`, `parties`, `acquirer`, `target` | the preamble and recitals |
| `governing_law` | the governing-law section |
| `outside_date` | the termination section |
| consideration amounts | the Article II share-conversion section |

A target whose section is not found is not retried and is recorded, never read from the whole
document. Each document makes at most one gap-retry call, and that call sends only the target items:
the target fields' schema slice and the target questions' answer lists. A target the retry still leaves
missing stays missing.

**With the judge's correct mode.** When a run sets `judge.mode: correct`, the judge's own field-only
retries stay the graph-level HF-027 retry they are today. With `question_groups` on, the MAUD questions
the judge names are re-asked per question from their sections, rather than as the whole `maud_clauses`
list. The confirming arm does not use correct mode (part 4).

### 4. The judge on mergers

The merger judge and arbiter loop is two to three whole-document reads in the baseline. The confirming
arm sets `confidence.by_class.merger_agreement.judge_max_passes: 0` and `arbiter_retry_max: 0`, so
mergers skip the judge loop. The gap retry takes its place.

The builder must prove offline, with the vendored graph, that a merger with `judge_max_passes: 0` and
these switches archives or goes to review on the vendored rules without crashing. If the vendored
routing does not honour 0, a small route rule in the merger hotfix skips the merger judge when
`question_groups` is on. Which way it goes is reported in preflight's routing audit.

### 5. Head reads for long documents (`job.long_document_head`)

The sorter and intake run before the document type is known, so this switch applies to every long
document, not just mergers.

**When it applies.** It applies to an API-routed sorter or intake read of a document over 150k
characters (in the dataset: 151 mergers, 36 contracts and 26 corporate records, of 3,302). The read
then sends only the document's opening, in one window, instead of the whole text. Today HF-010 would
fail that read with `WholeDocumentTooLong`; this switch replaces the failure with the head read. With
the switch off, behaviour is unchanged.

**How much it reads** (my calls, each a knob with these defaults):

- **Sorter: the first 120k characters, plus the last 8k.** The tail carries the signature page. On the
  34 calibration mergers, the Article II share-conversion section, which sets the consideration
  subclass, was found within the first 120k characters on all 32 where it was found (median offset
  22k, max 100k). At 80k it would miss 2.
- **Intake: the first 40k characters.** Intake's section map feeds only trace counts
  (`build_graph.py:659-693`), and its triage is an advisory prior for the sorter, so a shorter opening
  loses nothing downstream.

**What it records.** The read is marked `head_read` with the characters sent, in the trace and the run
items. It is a sandbox hotfix around the vendored sorter and intake window calls (HF-032), with HF-010
left installed for every read the switch does not cover.

### 6. Spend: whole-document reads per merger

The bar is billed dollars per merger document, over all its calls (sorter and intake included), with
cached tokens at the price actually billed. Tokens are reported alongside, from the two runs'
`usage_by_agent`.

| Path (median merger, about 85k tokens per whole read) | Whole-document reads (equivalent) | Tokens per doc |
|---|---|---|
| Stage-1 baseline: sorter, intake, 1 to 2 extractions, up to 2 judge passes, up to 1 arbiter | about 5 to 7 | 425k to 600k |
| Option 1 only (`merger.*`) | sorter 1 + intake 1 + main 1 + group excerpts about 0.3 + retry about 0.1 = **about 3.4** | about 290k |
| Option 1 + option 3 (`long_document_head`) | sorter about 0.38 + intake about 0.12 + main 1 + about 0.4 = **about 1.9** | about 160k |

These are source-length estimates, not measurements. The excerpt shares come from the offline locator
check (part 2), and preflight prints the plan's estimate per merger. `api_cost_cap_usd` stays the
baseline's 9.0.

### 7. Merger entity check (offline report)

Because a staged-overlay run cannot merge other labels, the check is an offline, read-only report,
modelled on `scripts/replay_attempt_hygiene.py`:

```text
python scripts/merger_entity_check.py --run <run> --labels <labels.jsonl> [--out <json>]
```

- **What it reads.** A finished pipeline run's merger extractions and a labels file. It never writes
  the run. It refuses a running checkpoint, a dataset that drifted from the lock, an output path inside
  the run and a missing file (the replay's refusals).
- **How it scores.** It scores the 16 entity fields plus `merger_consideration` with the Dojo field
  scorer and normalisation the gate already uses (dates, names, lists). The builder finds the
  per-field scorer the suite score uses (`suite_overall_extraction_score`) and calls it, never
  reimplementing comparison rules.
- **What it prints.** Per field: accuracy, labelled n and label source (`interim`, `near_gold`,
  `gold`). A field with no labels reads `unlabelled`, never 0. With two runs it prints paired per-field
  deltas on the same documents, next to their MAUD accuracy. The digest is labelled an offline check,
  not a headline.

**Labels.**

- **Interim (on main today).** `data/labels/interim/merger_agreement.jsonl` has 30 agreements and 4
  fields (document name, governing law, effective date and time), model gate-accepted. Only 9 of the 20
  stage-1 mergers have them.
- **Near-gold (to make).**
  - Scope: the 20 mergers the stage-1 baseline draws (dev-look1), over the 16 entity fields plus
    `merger_consideration`.
  - Add merger tiers to `gold_labels.target_fields` (empty for mergers today), so the existing
    near-gold workflow and `scripts/gold_labels.py` produce a work queue for these documents.
  - Every value needs a quote located in the document (`gold_labels.locate`).
  - Producing them is paid model work the owner launches. The output goes to
    `data/labels/gold-overlay/merger_agreement.jsonl`, with its MANIFEST entry, as for the other
    classes.
- **Human spot-check.**
  - A generated sample of 5 agreements (all their labelled fields) goes to a person.
  - The person marks each value right or wrong, and the result is recorded in the manifest.
  - Until it is recorded, the report marks every near-gold number `unverified`.
  - A spot-check under 90% agreement blocks citing the entity numbers.

The labels do not touch PR #425's files. If #425 later publishes merger labels in a staged overlay,
the report reads them in the same file format.

### 8. Confirming arms and adoption bars (owner-run)

**Arms.**

- **Merger arm, `config/runs/p5-s2-merger-reads.yaml`.** The stage-1 baseline `p4-s1-verify-gov-off`
  plus the three merger switches, `long_document_head`, and the merger judge settings, nothing else. A
  test pins that, as for `p5-s1-evidence-on`. Running all four together needs one paid pipeline run.
- **Classification check for the head reads, `config/runs/p5-s2-head-sorter-{off,on}.yaml`.** A paired
  `task: sorter` run on the long documents (over 150k characters) of the dev split, switch off versus
  on. It is cheap: one head read per document.

**Adoption bars** (on the paired documents):

- **MAUD accuracy:** a paired mean delta of at least +0.05, from the gate's paired per-class deltas
  (`gate_compare`). With n = 20 this is a direction check, not a significance claim, and the report
  says so.
- **Entity guard:** no entity field with at least 5 labels drops by more than 0.05.
- **Reads and spend:** merger whole-document-read equivalents at or below 2.5 per document, and billed
  dollars per merger at or below the baseline's.
- **Head reads:** the sorter check shows no class's classification accuracy and no merger subclass
  accuracy dropping by more than one document. Otherwise `long_document_head` is not adopted, and the
  merger switches are judged on their own.
- **Safety:** no new crashes or `judge_error` on mergers, and the other classes' extraction is
  unchanged.

If MAUD rises but the locator misses too often, widen its matching rules before considering
approach C.

## Measurement plan (owner-run, in order)

1. **Baseline.** Run stage 1 (`p4-s1-verify-gov-off`) from a checkout that includes this work. The
   switches are off, so it is the baseline, and its `usage_by_agent` gives the real merger cost.
2. **Offline locator check.** Run the part 2 check (no spend; can run before step 1).
3. **Labels.** Produce the near-gold merger labels (paid), then the human spot-check.
4. **Sorter check.** Run the paired sorter check (`p5-s2-head-sorter-off` and `-on`) with a person's
   initials.
5. **Merger arm.** Run `p5-s2-merger-reads` with a person's initials.
6. **Compare.**
   - `sandbox run gate` on the baseline and the arm;
   - `gate_compare` for MAUD;
   - `merger_entity_check.py` on both runs for the entity fields;
   - the per-step usage for the read count.

## Left to the builder

- **Hotfix boundaries.** By default:
  - HF-030: subclass fields, group reads and the gap retry, around `MergerAgreementSpecialist.extract`;
  - HF-031: per-question targets for the correct-mode retry, extending HF-027;
  - HF-032: head reads, around the sorter and intake window calls next to HF-010.

  The builder may merge or split them, with pinned sources and doc rows.
- **The switch-gated field-list section.** Where it lives, as long as `--check` covers it and the
  default lists are byte-identical.
- **The locator.** Its internal shape and the per-question merge's data shape, as long as the matching
  table is committed and generated from the Dojo hints.
- **The near-universal source counts.** The exact counts are the builder's; the list is generated,
  committed and calibration-only.
- **The preflight estimate.** The format of the offline read and cost estimate in preflight.
- **Tests,** each with a test that failed first. They must cover:
  - group ownership: each question is owned exactly once, for every `groups` value;
  - a locator miss: it keeps the main answer and never makes a whole-document read;
  - an enum rejection falling back;
  - a failed group read leaving the main read's answers;
  - entity fields unchanged by group reads;
  - a subclass disagreement re-asking the dropped field from its section;
  - a retry touching only its targets and reading only sections;
  - `judge_max_passes: 0` routing;
  - the head read replacing HF-010's failure only when the switch is on, and only over 150k characters;
  - spec hashing only when set;
  - a chunked read being left alone;
  - the near-universal list reading calibration documents only;
  - the entity report's refusals and its `unlabelled` reading;
  - each arm differing from the baseline only in its switches and the merger judge settings.
