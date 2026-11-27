# Phase 5 part 2: merger extraction with fewer whole-document reads — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Raise merger MAUD accuracy and cut a merger's whole-document reads from about 5–7 to about 2, with
subclass-valid fields, section-located MAUD question-group reads, one targeted gap retry, head reads for long
documents and an offline merger entity check, all off by default.

**Architecture:** Four switches in the run spec (`job.merger.{subclass_fields,question_groups,gap_retry,groups}`
and `job.long_document_head`) are locked and activated like `job.evidence_check`. The pipeline changes are sandbox
hotfixes:

- HF-030 wraps the merger specialist's `extract` for subclass fields, group reads and the gap retry.
- HF-031 extends HF-027's correct-mode retry to MAUD questions.
- HF-032 and HF-033 give the sorter and intake head reads.

Three deterministic, committed tables are generated from the Dojo by `--check`-able scripts:

- the subclass field section;
- the MAUD question groups and near-universal list;
- the section-matching rules.

Offline scripts check the section locator and score merger entity fields.

**Tech Stack:** Python 3.11, pydantic run spec, the vendored LangGraph pipeline (`vendor/llm-mailroom`, never
edited), Dojo `llm_dojo_scoring.schemas.maud_schema` (vendored), pytest.

**Spec:** [`docs/design/specs/2026-11-27-phase5-merger-maud-design.md`](../specs/2026-11-27-phase5-merger-maud-design.md)
(approved 2026-11-27). Read it with this plan; where they differ, the spec wins.

## Global Constraints

- Never edit `vendor/**`, `requirements/*.txt`, `uv.lock`, `.env`, `config/.env`, `data/runtime/` or `data/cache/`.
  Pipeline changes are hotfixes with pinned `source_sha256` and `also` pins, plus a row in
  `docs/vendor-hotfixes.md`.
- Hotfix IDs are HF-030 to HF-033. Reserve them in `docs/numbering-reservations.md` and set the next free ID to
  HF-034.
- No paid or live work, no `sandbox run start`, no `--real` or `--live`. Configs for the owner's arms are written,
  never launched.
- Every new switch is a `StrictBool` (and `groups` a `StrictInt`). Each is off by default, pipeline-only
  (`long_document_head` also for `task: sorter`), and hashed into `spec_hash` only when set. The baseline
  `p4-s1-verify-gov-off` keeps its literal hash.
- The default `config/extraction/subclass_extraction_fields.json` lists stay byte-identical. The merger section is
  separate and switch-gated.
- Never read a sealed held-out or dev document to build a committed table. Calibration mergers only
  (`config/splits/runbook-v2/assignments.jsonl`, `set == "calibration"`).
- A section locator miss never becomes a whole-document read.
- Entity fields come from the main (whole-document) read only. Group reads write only `maud_clauses`.
- These are the spec's own values. Sorter head: first 120,000 + last 8,000 characters. Intake head: first 40,000
  characters. Head-read threshold: documents over 150,000 characters. Excerpt cap: 24,000 characters per question,
  cut at a paragraph boundary and marked. Near-universal: at least 90% of calibration mergers. Default groups: 3.
- Local tests run named files only, as `.venv/bin/python -m pytest -q <files> -n 0 --no-cov`. Coverage floor 84.
- Commits follow `.gitmessage` (`type(scope): summary`, why, what changed, testing, refs) with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` only. No session links or footers, and no model
  identifiers.

## Review Focus

1. **An agreement whose table of contents repeats every heading.** The locator must take the body section, not the
   contents line. Expect an excerpt of the real section, or a miss.
2. **A document between 150,000 and about 600,000 characters that is not a merger,** such as a long contract. With
   `long_document_head` on, its sorter and intake reads are cut, and nothing else about it changes: its extraction
   still reads the whole document.
3. **A merger whose sorter subclass is `other` or low-confidence.** The full class schema is used, nothing is
   dropped, and group reads still run.
4. **A group read returning a line for a question it does not own,** or a free-text answer. The line is ignored,
   and the owning or main answer stands.
5. **A run resumed across this change.** The lock's `vendor_hotfixes` changes, and resume refuses without `--force`,
   naming HF-030 to HF-033 (existing behaviour; the test pins the message).

---

### Task 1: Spec switches, activation and reservations

**Files:**

- Create: `src/mailroom_sandbox/merger_reads.py`
- Modify: `src/mailroom_sandbox/job/spec.py` (job model near `evidence_check`, the `spec_core` hashing at the
  `evidence_check` exclusion, and validation near line 1398)
- Modify: `src/mailroom_sandbox/runtime.py`, next to `evidence_check.activate`
- Modify: `docs/numbering-reservations.md`
- Test: `tests/test_merger_reads_spec.py`

**Interfaces:**

- Produces:
  - `class MergerReads(BaseModel)`, with fields `subclass_fields: StrictBool = False`,
    `question_groups: StrictBool = False`, `gap_retry: StrictBool = False` and `groups: StrictInt = 3` (1 to 3).
  - On the job model: `merger: MergerReads | None = None` and `long_document_head: StrictBool = False`.
  - In `merger_reads`:
    - `activate(cfg: Mapping | None) -> None`
    - `config() -> dict | None`, which returns `{"subclass_fields", "question_groups", "gap_retry", "groups"}` or
      `None`
    - `on(name: str) -> bool`
    - `activate_head(enabled: bool) -> None` and `head_active() -> bool`

- [ ] **Step 1: Write the failing tests**

```python
def test_a_spec_without_the_switches_keeps_its_hash():  # baseline literal hash, as in the evidence-check test
    assert spec_hash(load("config/runs/p4-s1-verify-gov-off.yaml")) == BASELINE_HASH

def test_question_groups_require_subclass_fields():
    with pytest.raises(ValueError, match="job.merger.question_groups requires job.merger.subclass_fields"):
        RunSpec.model_validate(pipeline_spec(job={"merger": {"question_groups": True}}))

def test_gap_retry_requires_subclass_fields(): ...            # same shape, message names gap_retry

def test_groups_outside_one_to_three_is_refused():            # 0 and 4 both raise
    ...

def test_merger_switches_are_pipeline_only():                 # task: sorter with merger set raises
    ...

def test_long_document_head_is_allowed_on_sorter_and_pipeline_only():  # task: specialist raises
    ...

def test_a_set_switch_changes_the_hash_and_a_quoted_true_is_refused():
    ...

def test_activation_reads_the_locked_job():
    runtime_activate(lock(job={"merger": {"subclass_fields": True}, "long_document_head": True}))
    assert merger_reads.on("subclass_fields") and not merger_reads.on("question_groups")
    assert merger_reads.head_active()

def test_a_lock_without_the_keys_activates_nothing():
    ...
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest -q tests/test_merger_reads_spec.py -n 0 --no-cov`.
Expected: FAIL (no `merger_reads` module, unknown field).

- [ ] **Step 3: Implement**

- Add `MergerReads` and the two fields.
- Exclude `merger is None` and `long_document_head is False` from the job core, the same way `evidence_check` is
  excluded.
- Add validators with the exact messages above. Pipeline-only checks go beside the `evidence_check` one.
- In `runtime`, call `merger_reads.activate(locked_job.get("merger"))` and
  `merger_reads.activate_head(bool(locked_job.get("long_document_head")))`. An unlocked eval stays off.
- Reserve HF-030 to HF-033 in `docs/numbering-reservations.md`: HF-030 merger reads, HF-031 MAUD per-question
  correct-mode retry, HF-032 sorter head read, HF-033 intake head read. The next free ID is HF-034.

- [ ] **Step 4: Run them and watch them pass**

Run the same command plus `tests/test_job_spec.py tests/test_evidence_check.py`.
Expected: all pass.

- [ ] **Step 5: Commit** as `feat(merger): run-spec switches for merger reads and long-document head reads`.

### Task 2: Generated tables — subclass fields, MAUD groups, near-universal questions

**Files:**

- Create: `src/mailroom_sandbox/merger_tables.py`
- Create: `scripts/build_merger_tables.py`
- Create (generated, committed): `config/extraction/merger_tables.json`
- Test: `tests/test_merger_tables.py`

**Interfaces:**

- Consumes: Dojo `maud_schema.maud_questions()`, `consideration_subclass(token)` (pass the token string),
  `MAUD_CONSIDERATION_SUBCLASSES`; and `config/splits/runbook-v2/assignments.jsonl`.
- Produces: `config/extraction/merger_tables.json`, with schema id `mailroom.merger_tables/v1` and keys:
  - `subclass_drop: {subclass: [field, ...]}`
  - `groups: {"1": [question...], "2": [...], "3": [...]}`
  - `main_owned: [question...]`
  - `near_universal: {"questions": [...], "calibration_n": 34, "counts": {...}, "split_sha256": ...}`
  - `required_entities: [...]`
  - `entity_sections: {field: section_key}`
  - `merged_groups: {"1": ..., "2": ...}` (the layout for `groups` 1 and 2)
- Produces, in `merger_tables`:
  - `load() -> dict`
  - `sha256() -> str`
  - `dropped_fields(subclass: str) -> frozenset[str]`
  - `owner(question: str, groups: int) -> str` (`"main"` or a group key)
  - `group_questions(groups: int) -> dict[str, tuple[str, ...]]`
  - `near_universal() -> frozenset[str]`
  - `required_entities(subclass: str) -> tuple[str, ...]`

- [ ] **Step 1: Write the failing tests**

```python
def test_cash_drops_the_exchange_ratio_and_stock_drops_the_cash_amount():
    assert merger_tables.dropped_fields("all_cash") == {"exchange_ratio"}
    assert merger_tables.dropped_fields("all_stock") == {"per_share_cash_amount"}
    for sub in ("mixed_cash_stock", "mixed_cash_stock_election", "other"):
        assert merger_tables.dropped_fields(sub) == frozenset()

def test_every_question_has_exactly_one_owner_for_every_group_count():
    for n in (1, 2, 3):
        owners = [merger_tables.owner(q.name, n) for q in maud_questions()]
        assert len(owners) == 22 and all(owners)
        assert set(merger_tables.group_questions(n)) == {str(i) for i in range(1, n + 1)}

def test_the_main_read_owns_general_knowledge_mae_and_remedies():
    assert set(merger_tables.load()["main_owned"]) == {"Type of Consideration", "Knowledge Definition",
                                                       "MAE Definition", "Specific Performance"}

def test_the_near_universal_list_is_built_from_calibration_mergers_only(tmp_path):
    # a fixture assignments file putting a dev and a heldout merger at 100%; neither may change the list
    ...

def test_near_universal_matches_the_spec_on_todays_labels():   # skipped without the cached dataset
    assert len(merger_tables.near_universal()) == 11 and "MAE Definition" in merger_tables.near_universal()

def test_the_committed_tables_are_fresh():
    assert build_merger_tables.main(["--check"]) == 0

def test_required_entities_add_the_subclass_amount():
    assert merger_tables.required_entities("all_cash")[-1] == "per_share_cash_amount"
```

- [ ] **Step 2: Run them and watch them fail** (`tests/test_merger_tables.py`). Expected: import error.

- [ ] **Step 3: Implement the generator and the reader**

Subclass drop rule:

- From the two amount fields (`per_share_cash_amount`, `exchange_ratio`), keep those the subclass's `entity_hints`
  name. If it names neither, keep both. Drop the rest of the pair.

Group split:

- The Dojo groups other than Deal Protection map as follows:
  - Conditions to Closing and Operating and Efforts Covenant become group 3.
  - General Information, Knowledge, Material Adverse Effect and Remedies become `main`.
- Deal Protection is split by a committed list in the script:
  - Group 1: No-Shop; Fiduciary exception: Board determination (no-shop); Superior Offer Definition; Intervening
    Event Definition; Tail Period & Acquisition Proposal Details; Breach of No Shop.
  - Group 2: the other six.
- For `groups=2`, groups 1 and 2 merge. For `groups=1`, all non-main questions form one group.

Near-universal and the remaining tables:

- Near-universal: read `maud_clause_labels` from the cached ground-truth parquet for `set == "calibration"`
  mergers only. Keep questions at 90% or above. Record the counts and the assignments file's sha256.
- `required_entities`: `document_name, parties, acquirer, target, governing_law, outside_date`, plus the
  subclass's kept amount fields.
- `entity_sections`: `document_name, parties, acquirer, target → "preamble"`, `governing_law → "governing_law"`,
  `outside_date → "termination"`, both amounts `→ "consideration"`.
- `--check` exits 1 on a diff. The near-universal block is regenerated only when the dataset cache is present;
  otherwise `--check` compares everything else and says so.

- [ ] **Step 4: Run the build, then the tests.** Expected: the tests pass, and
  `python scripts/build_merger_tables.py --check` exits 0.

- [ ] **Step 5: Commit** as `feat(merger): generated merger tables (subclass fields, MAUD groups, near-universal
  questions)`.

### Task 3: Section locator and the offline locator check

**Files:**

- Create: `src/mailroom_sandbox/merger_sections.py`
- Create: `scripts/check_merger_sections.py`
- Create (committed rules): `config/extraction/merger_section_rules.json`
- Test: `tests/test_merger_sections.py` (fixture: `tests/fixtures/merger_sections/agreement.txt`, a synthetic
  agreement with a table of contents and articles)

**Interfaces:**

- Consumes: `MaudQuestion.sections` (the rules' source) and `merger_tables.entity_sections`.
- Produces:
  - `@dataclass(frozen=True) class Excerpt`, with fields `key: str`, `heading: str`, `start: int`, `end: int`,
    `text: str` and `cut: bool`.
  - `locate(doc_text: str) -> dict[str, Excerpt]`, keyed by rule key. A key it cannot find is absent.
  - `question_excerpts(doc_text: str, questions: Iterable[str]) -> tuple[list[Excerpt], list[str]]`, which
    returns the deduplicated excerpts and the missed questions.
  - `entity_excerpts(doc_text: str, fields: Iterable[str]) -> tuple[list[Excerpt], list[str]]`
  - `EXCERPT_CAP = 24_000`

- [ ] **Step 1: Write the failing tests**

```python
def test_the_body_section_is_found_not_the_table_of_contents():
    ex = merger_sections.locate(FIXTURE)["no_solicitation"]
    assert ex.start > FIXTURE.index("ARTICLE I") and "shall not, directly or indirectly" in ex.text

def test_a_defined_term_paragraph_runs_to_the_next_defined_term():
    ex = merger_sections.locate(FIXTURE)["def_mae"]
    assert ex.text.startswith('"Company Material Adverse Effect" means') and '"Knowledge" means' not in ex.text

def test_an_excerpt_over_the_cap_is_cut_at_a_paragraph_and_marked():
    ex = merger_sections.locate(LONG_FIXTURE)["conduct_of_business"]
    assert len(ex.text) <= merger_sections.EXCERPT_CAP and ex.cut and ex.text.endswith("\n")

def test_a_question_with_no_section_is_reported_missed():
    excerpts, missed = merger_sections.question_excerpts("no headings here", ["No-Shop"])
    assert excerpts == [] and missed == ["No-Shop"]

def test_two_questions_sharing_a_section_send_it_once():
    excerpts, _ = merger_sections.question_excerpts(FIXTURE, ["No-Shop", "Breach of No Shop"])
    assert len({e.key for e in excerpts}) == len(excerpts)

def test_every_maud_question_has_a_rule():
    rules = json.loads(Path("config/extraction/merger_section_rules.json").read_text())
    assert {q.name for q in maud_questions()} <= set(rules["questions"])
```

- [ ] **Step 2: Run them and watch them fail.**

- [ ] **Step 3: Implement**

The locator uses no model call and no network.

- Headings are lines matching `^(ARTICLE|Article)\s+[IVXLC\d]+` or `^(Section\s+)?\d+(\.\d+)+\s+\S`, with their
  following title words.
- The table of contents is the run of heading lines before the first heading followed by at least 400 characters
  of body text. Skip it.
- Defined terms are paragraphs starting `"<Term>" (shall )?mean`, ending at the next such paragraph or the next
  heading.

The rules file maps each question to rule keys. Each rule key has heading words or defined terms. It is hand-reviewed
from `MaudQuestion.sections`, and a test ties it to the Dojo question list. Excerpts run to the next heading of the
same or higher level, capped at `EXCERPT_CAP` and cut at the last blank line before the cap.

`scripts/check_merger_sections.py`:

- reads the cached dataset's calibration mergers only, read-only, with `python -I`;
- prints, per question, the found share, the median and maximum excerpt characters, and the estimated tokens per
  group read (characters / 4);
- lists every question under 80%;
- writes the full result to `data/runtime/merger_sections_check.json`.

- [ ] **Step 4: Run the tests, then the check script.** Expected: the tests pass. Record the script's digest in the
  ledger. If any question is under 80%, widen its rule words and re-run, and record a ruling for any question still
  under 80%.

- [ ] **Step 5: Commit** as `feat(merger): deterministic section locator and offline locator check`.

### Task 4: HF-030, merger reads in the specialist step

**Files:**

- Modify: `src/mailroom_sandbox/vendor_hotfixes.py` (new install function, plus a `Hotfix` entry after HF-029)
- Create: `src/mailroom_sandbox/merger_extract.py` (pure logic: prompts, schemas, combine, targets)
- Modify: `src/mailroom_sandbox/subclass_extraction.py`. When `merger_reads.on("subclass_fields")` and the class is
  `merger_agreement` on the confident-subclass path, `choose_schema` also drops
  `merger_tables.dropped_fields(subclass)`.
- Test: `tests/test_merger_extract.py` (pure) and `tests/test_merger_reads_hotfix.py` (vendored graph, with a fake
  structured call)

**Interfaces:**

- Consumes:
  - Task 1: `merger_reads.on`, `config`.
  - Task 2: `merger_tables.*`.
  - Task 3: `merger_sections.question_excerpts` and `entity_excerpts`.
  - Dojo `render_maud_question_block`, `parse_maud_clause`, `maud_question(name).valid_classes`.
  - `subclass_extraction._restrict`.
- Produces, in `merger_extract`:
  - `group_message(handoff: str | None, excerpts: list[Excerpt], subclass: str, questions: Sequence[str]) -> str`
  - `group_schema(questions: Sequence[str], *, enum: bool) -> dict`
  - `combine(main: dict, group_answers: Mapping[str, Sequence[str]], groups: int) -> tuple[list[str], list[str]]`,
    which returns `(maud_clauses, invalid_or_missing_questions)`
  - `gap_targets(extracted: dict, subclass: str, sorter_subclass: str, invalid: Sequence[str]) -> Targets`, where
    `Targets` holds `questions` and `fields`
  - Extraction marks: `_maud_group_failed: [group]`, `_maud_section_missed: [question]`,
    `_merger_reads: {"group_calls": int, "group_chars": int, "retry_chars": int, "targets": {...}}`
  - Ruling against the spec's `maud_group` usage tag: the vendored usage accumulator keys usage by agent name only,
    so group reads stay under `merger_agreement_specialist`. `_merger_reads` carries the split (calls and characters
    sent per group read and retry), and the cost comparison reads it. Record this in the ledger.

The hotfix wraps `agents.merger_agreement_specialist.MergerAgreementSpecialist.extract` (pin the inherited
`langchain_agents.specialist_agents._SpecialistBase.extract` source and `_call_structured`). A chunked read
(`self._last_chunked` true, or the call went to `extract_chunked`) is passed through untouched.

- [ ] **Step 1: Write the failing pure tests** (`tests/test_merger_extract.py`)

```python
def test_the_owning_group_answer_wins_and_the_main_answer_fills_a_gap(): ...
def test_a_line_for_a_question_the_group_does_not_own_is_ignored(): ...          # review focus 4
def test_a_free_text_answer_is_invalid_and_becomes_a_target(): ...
def test_the_group_block_comes_after_the_excerpts(): ...                          # shared opening
def test_the_group_schema_has_only_maud_clauses_with_an_enum_of_valid_lines():
    s = merger_extract.group_schema(["No-Shop"], enum=True)
    assert set(s["properties"]) == {"maud_clauses"}
    assert all(x.startswith("No-Shop: ") for x in s["properties"]["maud_clauses"]["items"]["enum"])
def test_gap_targets_take_invalid_answers_unanswered_near_universal_and_empty_required_fields(): ...
def test_a_subclass_disagreement_targets_the_dropped_amount():
    t = merger_extract.gap_targets({"merger_consideration": "all_stock", "exchange_ratio": None}, "all_cash", "all_cash", [])
    assert "exchange_ratio" in t.fields
```

- [ ] **Step 2: Write the failing hotfix tests** (`tests/test_merger_reads_hotfix.py`). They use the fake
  structured call that records every `(user_message, json_schema)` and returns scripted JSON.

```python
def test_off_by_default_the_specialist_makes_one_call(): ...
def test_three_group_calls_follow_the_main_read_and_send_only_excerpts():
    calls = run_merger(FIXTURE, cfg=ALL_ON)
    assert len(calls) == 4 + 1                       # main, 3 groups, 1 gap retry
    assert all(FIXTURE not in c.message for c in calls[1:])   # never the whole document again
def test_a_locator_miss_keeps_the_main_answer_and_never_reads_the_whole_document(): ...
def test_a_group_with_no_located_question_makes_no_call(): ...
def test_an_enum_rejection_falls_back_to_the_plain_list(): ...
def test_a_failed_group_read_leaves_the_main_answers_and_is_recorded(): ...
def test_group_reads_never_change_an_entity_field(): ...
def test_the_gap_retry_asks_only_its_targets_from_sections(): ...
def test_without_gap_retry_a_subclass_disagreement_asks_the_dropped_field_alone(): ...
def test_a_chunked_read_is_left_alone(): ...
def test_an_other_or_low_confidence_subclass_drops_nothing_and_still_runs_groups(): ...  # review focus 3
def test_a_document_that_is_not_a_merger_is_untouched(): ...
def test_hf030_is_registered_with_a_pinned_source(): ...
```

- [ ] **Step 3: Run both files and watch them fail.**

- [ ] **Step 4: Implement `merger_extract` and the HF-030 install.**

All extra calls go through the instance's `_call_structured` (so HF-023's swap, the call guard, the governor and
usage capture see them), with `pages=None`. The shape of one merger read:

```text
result = original_extract(self, doc_text, pages)              # main read: unchanged frozen prompt + subclass schema
if not merger_reads.on("question_groups") or chunked: maybe_dropped_field_call(); return result
for group, questions in merger_tables.group_questions(cfg["groups"]).items():
    excerpts, missed = merger_sections.question_excerpts(doc_text, questions)
    asked = [q for q in questions if q not in missed]
    if asked: answers[group] = call(group_message(...), group_schema(asked, enum=True)) (enum fallback on a 400)
result["maud_clauses"], invalid = combine(result, answers, groups)
if gap_retry: targets = gap_targets(...); one call with _restrict(schema, targets.fields) + target questions' block, from sections
record marks; return result
```

The `subclass_extraction` change:

- `choose_schema(..., merger_drop=frozenset())` drops the extra fields only on the `"subclass"` path, and the
  reason becomes `"subclass+merger"`.
- The fallback paths are unchanged.

- [ ] **Step 5: Run both files, plus `tests/test_subclass_extraction.py`, `tests/test_vendor_hotfixes.py` and
  `tests/test_evidence_check.py`.** Expected: all pass. `python scripts/check_hotfixes.py` reports HF-030 applied.

- [ ] **Step 6: Commit** as `feat(merger): HF-030 section-located MAUD question-group reads and gap retry`.

### Task 5: Merger judge settings and the correct-mode MAUD retry (HF-031)

**Files:**

- Modify: `src/mailroom_sandbox/vendor_hotfixes.py` (HF-031 install, extending HF-027's merge for per-question
  targets)
- Test: `tests/test_merger_judge.py`

**Interfaces:**

- Consumes: HF-027 `_FIELD_RETRY`, `correcting_judge.last_ruling()`, Task 4's `merger_extract.combine`.
- Produces: with `question_groups` on, a correct-mode `retry_fields` entry naming a MAUD question (`"maud:<Question>"`
  or the question name inside `maud_clauses`; settle by reading what HF-025's ruling schema emits) re-asks only that
  question from its excerpts. All other `maud_clauses` lines keep their values.

- [ ] **Step 1: Write the failing tests**

```python
def test_judge_max_passes_zero_skips_the_merger_judge_and_archives_or_reviews_without_crashing():
    # the vendored graph, mocked specialist; by_class.merger_agreement judge_max_passes 0, arbiter_retry_max 0
    final = run_graph(MERGER_DOC, thresholds=ZERO_JUDGE)
    assert final["judge_pass_count"] == 0 and final["route"] in {"archive", "human_review"}
def test_the_routing_audit_reports_the_merger_judge_off(): ...
def test_a_correct_mode_retry_naming_one_maud_question_replaces_only_that_line(): ...
def test_hf031_is_inert_without_question_groups(): ...
```

- [ ] **Step 2: Run them and watch them fail.** If the first test already passes on the vendored routing, record
  `Ruling: vendored routing honours judge_max_passes 0` and keep the test as a guard. Otherwise, add the route rule
  `HF-030:merger_judge_off` under HF-030 and re-run.

- [ ] **Step 3: Implement HF-031 and, only if needed, the route rule.**

- [ ] **Step 4: Run** `tests/test_merger_judge.py tests/test_correcting_judge.py tests/test_vendor_hotfixes.py`.
  Expected: all pass.

- [ ] **Step 5: Commit** as `feat(merger): merger judge off and per-question correct-mode MAUD retry (HF-031)`.

### Task 6: Head reads for long documents (HF-032 sorter, HF-033 intake)

**Files:**

- Modify: `src/mailroom_sandbox/vendor_hotfixes.py`. HF-032 wraps `agents.sorter.SorterAgent.classify_json`, and
  HF-033 wraps `agents.intake.IntakeAgent.intake_run`. Both pin HF-010's `sliding_windows`.
- Test: `tests/test_long_document_head.py`

**Interfaces:**

- Consumes: `merger_reads.head_active()`, the existing `_api_route(agent_name)`.
- Produces:
  - `HEAD_THRESHOLD = 150_000`, `SORTER_HEAD = 120_000`, `SORTER_TAIL = 8_000`, `INTAKE_HEAD = 40_000` (module
    constants in `merger_reads`)
  - `head_text(text: str, head: int, tail: int) -> str`, which joins the head and tail with the marker line
    `"\n\n[… <n> characters of the document omitted …]\n\n"`
  - The read mark: a `head_read` entry, `{"agent": ..., "chars_sent": int, "doc_chars": int}`, recorded in the
    trace and the run item.

- [ ] **Step 1: Write the failing tests**

```python
def test_off_by_default_a_long_document_still_reads_whole(): ...
def test_on_a_sorter_read_over_the_threshold_sends_head_and_tail_only():
    sent = sorter_input("x" * 400_000)
    assert len(sent) < 130_000 and sent.startswith("x" * 1000) and "characters of the document omitted" in sent
def test_a_document_at_or_under_the_threshold_is_untouched(): ...
def test_intake_reads_only_the_first_forty_thousand(): ...
def test_a_self_hosted_route_is_left_to_its_windows(): ...
def test_a_long_contract_extraction_still_reads_the_whole_document(): ...         # review focus 2
def test_hf010_still_refuses_a_multi_window_read_when_the_switch_is_off(): ...
def test_the_head_read_is_recorded(): ...
```

- [ ] **Step 2: Run them and watch them fail.**

- [ ] **Step 3: Implement both installs.** Cut `doc_text` before the vendored method runs. Only an API route
  qualifies, only when `head_active()`, and only over `HEAD_THRESHOLD`.

- [ ] **Step 4: Run** `tests/test_long_document_head.py tests/test_vendor_hotfixes.py`. Expected: all pass.
  `scripts/check_hotfixes.py` reports HF-032 and HF-033 applied.

- [ ] **Step 5: Commit** as `feat(intake): HF-032/HF-033 head reads for long documents`.

### Task 7: Merger entity check, near-gold tiers and the spot-check sample

**Files:**

- Create: `src/mailroom_sandbox/job/merger_entities.py`
- Create: `scripts/merger_entity_check.py`
- Modify: `src/mailroom_sandbox/gold_labels.py`, adding `TARGET_FIELDS["merger_agreement"]`. Tier 1 is the 16 entity
  fields; tier 2 is `merger_consideration`.
- Create: `scripts/merger_spot_check.py`
- Test: `tests/test_merger_entities.py`

**Interfaces:**

- Consumes:
  - `rescore.locate`, the replay's refusal helpers (`attempt_replay._verify_dataset`, `rescore._finished_lock`);
  - `eval.scoring.score_extraction_row(..., field_scores=True)` for per-field scores;
  - label files in the interim or gold-overlay JSONL format (`labels[field].value`, `use_as_truth`, `basis`).
- Produces:
  - `check(run: str | Path, labels: Path | Sequence[Path], *, baseline: str | Path | None = None) -> dict`
  - `write_check(result, path, *, source) -> Path` (refuses a path inside the run)
  - `digest(result, path) -> str`, labelled "offline entity check (not the headline)"
  - Per field: `{"accuracy": float | None, "n": int, "source": "interim" | "near_gold" | "gold", "status":
    "scored" | "unlabelled"}`
  - With a baseline: `paired_delta` per field, plus both runs' MAUD accuracy.
  - `scripts/merger_spot_check.py --labels <file> --n 5 --seed <int>` writes a review sheet to
    `data/runtime/merger_spot_check/`. Its `--record <sheet>` writes the agreement rate into the label MANIFEST
    entry. Below 0.90 it sets `"cite_blocked": true`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_field_with_no_labels_reads_unlabelled_not_zero(): ...
def test_fields_are_scored_by_the_suite_scorer_not_a_local_comparison(monkeypatch): ...   # spy on score_extraction_row
def test_near_gold_numbers_are_unverified_until_the_spot_check_is_recorded(): ...
def test_a_spot_check_under_ninety_percent_blocks_citing(): ...
def test_paired_deltas_use_only_documents_in_both_runs(): ...
def test_it_refuses_a_running_run_a_drifted_dataset_an_output_inside_the_run_and_a_missing_file(): ...
def test_it_never_writes_the_source_run(): ...
def test_merger_target_fields_are_the_sixteen_entities_and_the_consideration():
    assert len(gold_labels.target_fields("merger_agreement")) == 17
```

- [ ] **Step 2: Run them and watch them fail.**

- [ ] **Step 3: Implement.** Mirror `attempt_replay`'s structure and refusals. Read only; no model call.

- [ ] **Step 4: Run** `tests/test_merger_entities.py tests/test_attempt_replay.py tests/test_gold_labels.py`
  (`test_gold_labels.py` only if it exists). Expected: all pass. The script runs end to end on a fixture run.

- [ ] **Step 5: Commit** as `feat(merger): offline merger entity check with near-gold tiers and a spot-check sample`.

### Task 8: Confirming arms, preflight estimate, docs and the full gate run

**Files:**

- Create: `config/runs/p5-s2-merger-reads.yaml`, `config/runs/p5-s2-head-sorter-off.yaml` and
  `config/runs/p5-s2-head-sorter-on.yaml`
- Create (if the existing ids tooling cannot select by length): `config/splits/runbook-v2/dev-long.exclude.ids`,
  generated with its own builder
- Modify: `src/mailroom_sandbox/job/preflight.py`. Add a `merger_reads` block, which reports the switches, the
  merger judge settings and the estimated whole-read equivalents per merger. The estimate is (sorter + intake head
  shares + 1 + group excerpt chars / doc chars + retry), on the drawn mergers' characters.
- Modify docs:
  - `docs/vendor-hotfixes.md` (rows HF-030 to HF-033);
  - `docs/EXPERIMENT-CAMPAIGN-CONTRACT.md` (the hotfix rows);
  - `docs/jobs.md` (new section "Merger reads and long-document head reads (Phase 5 part 2)");
  - `docs/critical-regressions.md` (guard names on rows 2, 5, 6, 8 and 9);
  - `CHANGELOG.md`;
  - `docs/README.md` (link the plan);
  - this plan's checkboxes.
- Test: `tests/test_merger_arms.py`

**Interfaces:**

- Consumes: everything above.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_merger_arm_differs_from_the_baseline_only_in_its_switches_and_the_merger_judge():
    diff = spec_diff("config/runs/p4-s1-verify-gov-off.yaml", "config/runs/p5-s2-merger-reads.yaml")
    assert diff == {"run_id", "job.merger", "job.long_document_head",
                    "confidence.by_class.merger_agreement.judge_max_passes",
                    "confidence.by_class.merger_agreement.arbiter_retry_max", "trace.tags"}
def test_the_sorter_arms_differ_only_in_the_head_switch(): ...
def test_the_sorter_arms_draw_only_documents_over_the_threshold_from_dev(): ...
def test_preflight_reports_the_merger_reads_block_and_estimate(): ...
def test_a_resume_after_this_change_names_the_new_hotfixes(): ...                   # review focus 5
```

- [ ] **Step 2: Run them and watch them fail.**

- [ ] **Step 3: Write the configs and the preflight block.** Each header comment says to launch only with a person's
  initials, and gives the measurement plan from spec §8. The arm keeps `api_cost_cap_usd: 9.0`. Then write the docs.

- [ ] **Step 4: Run every touched and neighbouring test file in one command**, with the files listed inline:
  `test_merger_reads_spec test_merger_tables test_merger_sections test_merger_extract test_merger_reads_hotfix
  test_merger_judge test_long_document_head test_merger_entities test_merger_arms test_job_spec test_job_preflight
  test_job_runner test_vendor_hotfixes test_vendor_drift test_evidence_check test_correcting_judge
  test_subclass_extraction test_attempt_replay test_rescore test_routing_calibration test_docs_drift
  test_production_slices test_pipeline_graph test_gate`, each as `tests/<name>.py`, keeping only the files that
  exist. Expected: all pass.

Then run every local gate:

- `ruff check src tests scripts deploy reports notebooks`
- `bandit -q -ll -r src deploy scripts`
- `yamllint -c .yamllint.yaml .`
- `python scripts/sync_requirements.py --check`
- `python reports/dashboard/build_hub.py --check`
- `python scripts/check_cli_surface.py --check`
- `python scripts/check_hotfixes.py`
- `sandbox runbook check`
- `sandbox report build --campaign rb1 --check`
- `python scripts/build_subclass_fields.py --check`
- `python scripts/build_merger_tables.py --check`
- `python scripts/build_judge_reference_pool.py --check`
- `npx -y markdownlint-cli2@0.18.1`

Each must exit 0.

- [ ] **Step 5: Commit** as `feat(merger): confirming arms, preflight estimate and docs for Phase 5 part 2`.

## After the tasks

- A fresh whole-branch review on the most capable model (`superpowers:requesting-code-review`), plus the
  `pr-domain-reviewer` agent. Fix Critical and Important findings with a test that fails first.
- Open one PR, using the template and pointing at this plan and the spec, with Critical regressions filled. Merge
  only when hosted CircleCI is green on the head, and with the owner's go-ahead.
- Owner-run, in order (spec "Measurement plan"):
  1. the baseline;
  2. the locator check;
  3. the near-gold labels and spot-check;
  4. the sorter arms;
  5. the merger arm;
  6. the comparison.
