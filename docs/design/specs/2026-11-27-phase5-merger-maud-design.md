# Phase 5 part 2: better merger extraction at today's spend

Status: design, for owner approval. Builds on
[the correcting-judge design](2026-11-26-correcting-judge-design.md) (Phase 5, D1/D2) and
[Phase 5 part 1](2026-11-27-phase5-attempt-hygiene-design.md), re-scoped to the OpenRouter production
route (`qwen/qwen3.7-flash`, 1M context, one-call whole-document reads).

## Why

Merger agreements are the weakest and most expensive class on the production route:

- **Quality.** The merger headline is MAUD accuracy alone (`eval/scoring.py:329`), and it sits at
  0.09 to 0.11 in every run so far: the E3 control (0.106), SAND-214 with the tuned `maud_v2` prompt
  (0.091) and the Qwen-25 audit (7 of 79 answers).
- **Cost.** About 74% of a mixed run's tokens. The autoresearch `mailroom-v1` run recorded per-step
  usage for 5 whole-document mergers: about 590k prompt tokens each, over roughly 7 whole-document reads
  per document (median merger about 340k characters, about 85k tokens).

| Step (mailroom-v1, 5 mergers) | Calls per doc | Prompt tokens per doc | Share |
|---|---|---|---|
| judge | 3.0 | 233k | 39% |
| merger specialist | 1.8 | 138k | 23% |
| sorter | 1.0 | 80k | 13% |
| intake | 1.0 | 77k | 13% |
| arbiter | 0.8 | 61k | 10% |

Half the tokens go to the judge and arbiter, which have not improved a merger result: the Qwen-25
audit found the judge passed 0 of 8 mergers and 0 of 4 retries improved a verdict. That half is the
budget for a better read.

The likely cause of the low score is the read itself. One call is asked 22 detailed legal questions,
each with a fixed answer list of 2 to 95 classes, about an 85k-token agreement, at the same time as 16
entity fields. Chunking does not help MAUD: each question has one answer, so chunks return competing
answers (9 conflicts on one 14-window Qwen-25 read; SAND-214's chunked reads averaged 0.091).

## What the owner decided

- **Raise MAUD accuracy, and spend no more than today** (approach B below). Confirmation needs a paid
  run, which the owner launches.
- **Use the designated merger schema.** That is the Dojo's `MergerAgreementExtraction`
  (`maud_schema.py`, schema id `merger_agreement@v9.3`, 21 fields). Capture **only the fields that are
  valid for the document's subclass**.
- **Retries target only what the first round did not cover or got wrong**, never the whole extraction.
- **Add an entity-field check for mergers**, reported next to MAUD, not in the headline.
- **Labels for the entity check:** near-gold labels now (the repo's two-agreeing-passes or Opus-review
  path), plus a human spot-check of a sample before anyone cites the numbers.

## Goals, non-goals and anti-goals

Goals:

1. A higher paired MAUD accuracy on the stage-1 mergers, at merger tokens per document no higher than
   the stage-1 baseline's.
2. Each merger subclass is asked only for its valid fields, from the Dojo's own definitions.
3. A retry re-asks only the missing or invalid items, and changes nothing else.
4. A measured entity-field accuracy for mergers, with its label source and n stated.

Non-goals:

- Any other class. Contracts got part 1. A shared mechanism may be reused later but is not built for
  them here.
- Changing the merger headline (stays MAUD accuracy) or any scorer. Dojo owns scoring.
- New prompt versions. Frozen prompts stay frozen; any added instruction is generated deterministic
  text, as the subclass field note does (`docs/design/plans/2026-11-27-subclass-field-note.md`).
- Trimming the sorter. It runs before the class is known, so a cap would change every class, and blind
  routing still misclassifies some mergers (`classification:wrong_class` on 3 to 9 of 15 in
  `mailroom-v2`).

Anti-goals (a failure even if the code works):

- Entity fields get worse because MAUD moved to other reads.
- A wrong sorter subclass silently drops a field the document does have.
- The new reads cost more than the judge loop they replace.
- A replay, mock or estimate is cited as a quality result.
- The stage-1 baseline changes behaviour. Everything here is off unless a run sets it.

## Constraints

- Offline build: no paid or live work from an agent. The owner runs the stage-1 baseline and the
  confirming arm with their own initials.
- `vendor/` is never edited. Pipeline changes are sandbox hotfixes (next free IDs: HF-030, HF-031;
  reserve both in `docs/numbering-reservations.md`), each with a pinned source and a
  `docs/vendor-hotfixes.md` row.
- Mesh with open PRs; touch nothing on #425, #430, #437 or #439. The rc.10 labels on #425 are read only.
- A run scored with `dataset.staged_overlay` cannot also merge interim or near-gold labels
  (`job/spec.py:184`). The stage-1 runs use rc.10, so the entity check cannot ride on the run's truth.
- Every new switch is a `StrictBool`, pipeline runs only, hashed into `spec_hash` only when set (the
  `job.evidence_check` pattern), so existing locks and the baseline's hash are unchanged.
- Coverage floor 84; local tests are named files with `-n 0 --no-cov`.

## Approaches considered

| | Approach | Trade-off | Verdict |
|---|---|---|---|
| A | Chunked read with the evidence merge (E1's 1.8× read) | Proven for contract clause lists, where each chunk adds items. MAUD answers are one-per-question, so chunks conflict; past chunked merger reads scored 0.09 to 0.10 | Rejected |
| **B** | **One whole-document read per MAUD question group, paid for by dropping the merger judge loop** | Each question asked exactly once, with only its group's answer list; no conflicts. About 4 reads where there was 1, roughly what the judge loop cost | **Chosen** |
| C | Locate clauses first, then answer from the quotes | Cheapest (about 1.1 reads) and checkable, but depends on clause finding that is unproven on this model | Fallback if B's measured cost is too high |

## The design

Three switches under one new spec block, all off by default, so a later ablation can attribute any
gain:

```yaml
job:
  merger:
    subclass_fields: true    # only the fields valid for the subclass (part 1 below)
    question_groups: true    # MAUD answered in group reads (part 2)
    gap_retry: true          # one targeted retry for missing or invalid items (part 3)
```

`question_groups` and `gap_retry` require `subclass_fields` (they use its field set). All three apply
only to documents routed to `merger_agreement_specialist` on a one-call read. A chunked read (Modal or
local routes) keeps today's behaviour, and preflight says so.

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

Rule (generated, never hand-listed): of the two consideration-amount fields, keep those the subclass's
entity hints name; when it names neither, keep both. Derive this in `scripts/build_subclass_fields.py`
as a separate, switch-gated section of the committed field lists, so `--check` keeps it fresh and the
default lists (and the baseline) are unchanged. The subclass's priority questions
(`ConsiderationSubclass.priority_questions`) set the question order in part 2. Every MAUD question
stays valid for every subclass (the Dojo marks none invalid).

Hint fields that are not in the schema (`cvr`, `cash_in_lieu_of_fractional_shares`,
`election_mechanics`, `proration`, `consideration_description`) are not added. They would be unscored,
and the owner asked to capture only valid schema fields. (My call; easy to revisit.)

**A wrong subclass must not lose a field.** The main read still extracts `merger_consideration`. When
its token disagrees with the sorter's subclass (using the Dojo's `equivalent_to`), the field the
sorter's subclass dropped becomes a gap-retry target (part 3), so the document is not left without it.

### 2. Question-group reads (`job.merger.question_groups`)

The main read is unchanged: the frozen prompt, the subclass schema and the whole document. It fills the
entities, the consideration and a first answer to every MAUD question. Then up to three group reads
each re-ask one MAUD group over the whole document:

| Read | MAUD questions (Dojo `group`) | Count |
|---|---|---|
| main | all (fallback answers); its own answers stand for General Information, Knowledge, MAE, Remedies | 22 (4 owned) |
| group 1 | Deal Protection: no-shop, fiduciary outs, superior offer, intervening event, tail period, breach of no-shop | 6 |
| group 2 | Deal Protection: matching rights (COR, FTR), FTR triggers, limitations on FTR, fiduciary exception to COR, breach of meeting covenant | 6 |
| group 3 | Conditions to Closing and Operating and Efforts Covenant | 6 |

The grouping is my call. It splits the Dojo's 12-question Deal Protection group in two, keeps each read
at 4 to 6 questions, and puts MAE (40 classes) in the main read on its own group. The builder may
rebalance as long as each question is owned by exactly one read and the table is generated from the
Dojo's `group` field plus one committed split list.

Each group read:

- sends the same system prompt and the whole document, plus a generated instruction block from the
  Dojo's `render_maud_question_block(subclass, shape="lines", questions=<group>, chunked=False)`: the
  group's questions with every allowed answer verbatim;
- uses a response schema with only `maud_clauses`, whose items are constrained to the group's valid
  `"<Question>: <answer>"` lines (an enum built from `valid_classes`). If the provider rejects the enum,
  fall back to the unconstrained list and validate after;
- goes through the same specialist call path, so the call guard, governor, spend cap and usage capture
  count every call (usage is attributed to `merger_agreement_specialist`, with a `maud_group` tag so the
  cost report can split it).

**Combining.** For each question, the owning read's valid answer wins. A question its owner left
unanswered or answered invalidly falls back to the main read's valid answer, then to a gap retry.
Answers are normalised and validated with the Dojo's `parse_maud_clause`. Only `maud_clauses` changes;
every entity field comes from the main read alone (the anti-goal guard). The merged extraction then goes
through `_enrich_contract_result` like any other, so the guard, conflict check, attempt history and
HF-029 see one extraction.

A group read that fails (parse error, transport error after the usual transient retry, budget refusal)
leaves the main read's answers for its questions, records `_maud_group_failed`, and never fails the
document.

### 3. Gap retry (`job.merger.gap_retry`)

After the main read and group reads, one retry call re-asks only the items that are missing or
invalid, using the HF-027 mechanism (`subclass_extraction.fields_only` plus the merge that replaces only
the named items). For MAUD, the targets are named per question, not the whole `maud_clauses` field.
Targets:

1. A MAUD answer that is not one of its question's valid answers (definite error).
2. A near-universal MAUD question left unanswered. Near-universal means labelled on at least 90% of
   merger agreements **in the train split, excluding every document a stage-1 or confirming run can
   draw** (no leakage). On today's whole-dataset counts that is 9 questions: Accuracy of Target R&W,
   MAE Definition, Tail Period, Ordinary course covenant, Fiduciary exception to COR, Negative interim
   operating covenant, matching rights for COR, Superior Offer Definition and Knowledge Definition. The
   list is generated and committed with its source counts.
3. A required entity field, valid for the subclass, that came back empty. Required means a field every
   executed merger agreement states. My call, as a committed list: `document_name`, `parties`, `acquirer`,
   `target`, `governing_law` and `outside_date`, plus the subclass's consideration-amount field(s).
4. The dropped consideration field after a subclass disagreement (part 1).
5. When `judge.mode: correct` is on, the judge's `retry_fields`. MAUD questions it names are targeted
   per question.

At most one gap-retry call per document. It sends only the target items: the target fields'
schema slice, and the target questions' answer lists. A target the retry still leaves missing stays
missing. The retry counts against the governor's retry and call budgets like any other.

### 4. The judge on mergers

The merger judge and arbiter loop is where the budget comes from. The confirming arm sets
`confidence.by_class.merger_agreement.judge_max_passes: 0` and `arbiter_retry_max: 0`, so mergers
skip the judge loop. The gap retry takes its place.

The builder must prove offline, with the vendored graph, that a merger with `judge_max_passes: 0` and
these switches archives or goes to review on the vendored rules without crashing. If the vendored
routing does not honour 0, a small route rule in HF-030 skips the merger judge when `question_groups`
is on. Which way it goes is reported in preflight's routing audit.

### 5. Spend

The target: confirming-arm merger tokens per document no higher than the baseline's, read from the
two runs' `usage_by_agent`.

| Path (per merger, median about 85k tokens) | Whole-document reads |
|---|---|
| Today (mailroom-v1): sorter, intake, 1.8 specialist, 3 judge, 0.8 arbiter | about 7.6 |
| This design: sorter, intake, main, 3 group reads, at most 1 gap retry (sliced output, whole input) | 6 to 7 |

The estimate is a source-length estimate, not a measurement. To hold the target if the baseline is
cheaper than mailroom-v1:

- preflight prints the estimated merger reads per document from the plan;
- the group count is a knob (`job.merger.groups: 3`, range 1 to 3);
- `api_cost_cap_usd` stays the baseline's 9.0.

### 6. Merger entity check (offline report)

Because a staged-overlay run cannot merge other labels, the check is an offline, read-only report,
modelled on `scripts/replay_attempt_hygiene.py`:

```text
python scripts/merger_entity_check.py --run <run> --labels <labels.jsonl> [--out <json>]
```

- It reads a finished pipeline run's merger extractions and a labels file, and never writes the run.
  It refuses a running checkpoint, a dataset that drifted from the lock, an output path inside the run
  and a missing file (the replay's refusals).
- It scores the 16 entity fields plus `merger_consideration` with the Dojo field scorer and
  normalisation the gate already uses (dates, names, lists). The builder finds the per-field scorer the
  suite score uses (`suite_overall_extraction_score`) and calls it, never reimplementing comparison
  rules.
- Output per field: accuracy, labelled n and label source (`interim`, `near_gold`, `gold`). A field
  with no labels reads `unlabelled`, never 0. With two runs it prints paired per-field deltas on the
  same documents, next to their MAUD accuracy. The digest is labelled an offline check, not a headline.

**Labels.**

- **Interim (on main today).** `data/labels/interim/merger_agreement.jsonl`: 30 agreements and 4
  fields (document name, governing law, effective date and time), model gate-accepted. Only 9 of the 20
  stage-1 mergers have them.
- **Near-gold (to make).**
  - The scope is the 20 mergers the stage-1 baseline draws (dev-look1), over the 16 entity fields plus
    `merger_consideration`.
  - Add merger tiers to `gold_labels.target_fields` (empty for mergers today), so the existing
    near-gold workflow and `scripts/gold_labels.py` produce a work queue for these documents.
  - Every value needs a quote located in the document (`gold_labels.locate`).
  - Producing the labels is paid model work, which the owner launches. The output goes to
    `data/labels/gold-overlay/merger_agreement.jsonl` with its MANIFEST entry, as for the other classes.
- **Human spot-check.**
  - A generated sample of 5 agreements, with all their labelled fields, goes to a person.
  - The person marks each value right or wrong, and the result is recorded in the manifest.
  - Until it is recorded, the report marks every near-gold number `unverified`.
  - A spot-check under 90% agreement blocks citing the entity numbers.

The labels do not touch PR #425's files. If #425 later publishes merger labels in a staged overlay,
the report reads them by the same file format.

### 7. Adoption bars (the owner's confirming arm)

New config `config/runs/p5-s2-merger-reads.yaml`: the stage-1 baseline `p4-s1-verify-gov-off` plus the
three switches and the merger judge settings, and nothing else (a test pins that, as for
`p5-s1-evidence-on`). Adopt when all of these hold on the paired mergers:

- **MAUD accuracy:** paired mean delta of at least +0.05, from the gate's paired per-class deltas
  (`gate_compare`). With n = 20 this is a direction check, not a significance claim, and the report
  says so.
- **Entity guard:** no entity field with at least 5 labels drops by more than 0.05.
- **Spend:** merger tokens per document at or below the baseline's.
- **Safety:** no new crashes or `judge_error` on mergers, and the other classes are unchanged. This
  arm only changes the merger path.

If MAUD rises but spend is over, re-run with fewer groups before considering approach C.

## Measurement plan (owner-run, in order)

1. Run stage 1 (`p4-s1-verify-gov-off`) from a checkout that includes this work. The switches are off,
   so it is the baseline. Its `usage_by_agent` gives the real merger cost.
2. Produce the near-gold merger labels (paid) and the human spot-check.
3. Run `p5-s2-merger-reads` with a person's initials.
4. Run `sandbox run gate` on both runs, `gate_compare` for MAUD, and `merger_entity_check.py` on both
   runs for the entity fields.

## Left to the builder

- Hotfix boundaries: HF-030 (subclass fields and group reads around `MergerAgreementSpecialist.extract`)
  and HF-031 (gap retry around `retry_extract_node`, extending HF-027). The builder may merge or split
  them, with pinned sources and doc rows.
- Where the switch-gated field-list section lives, as long as `--check` covers it and the default
  lists are byte-identical.
- The per-question merge's internal data shape, and how `fields_only` carries question names.
- The near-universal threshold's exact source counts. The list is generated, committed and leakage-safe.
- The offline cost estimate's format in preflight.
- Tests (each with a test that failed first). They must cover:
  - group ownership: each question owned exactly once;
  - an enum rejection falling back;
  - a failed group read leaving the main read's answers;
  - entity fields unchanged by group reads;
  - a subclass disagreement making a gap target;
  - a retry touching only its targets;
  - `judge_max_passes: 0` routing;
  - spec hashing only when set;
  - a chunked read being left alone;
  - the entity report's refusals and the `unlabelled` reading;
  - the arm differing from the baseline only in the switches and the merger judge settings.
