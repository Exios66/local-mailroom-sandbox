# Phase 3: Subclass Extraction Schemas (X1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Behind `job.subclass_schemas`, each extraction call asks for the predicted subclass's schema (the class schema without the fields the Dojo marks not applicable to that subclass, plus labeled extension fields), and falls back to the class schema when the subclass is unknown or the sorter is unsure.

**Architecture:**

- A committed field list, `config/extraction/subclass_extraction_fields.json`, is derived from the label registry `config/extraction/subclass_schemas.json` by a pure builder that never reads held-out counts.
- A pure selector turns (class, predicted subclass, confidence, class schema) into the schema to send.
- One vendor hotfix, HF-023, picks the schema when `extract_node` builds its handoff. It swaps the schema into the specialist's structured call only for the duration of that extraction. `vendor/` is not edited.

**Tech Stack:** Python 3.11, pydantic (job spec), `contextvars`, pytest. The vendored `llm-mailroom` graph and specialists and the vendored `llm-dojo-scoring` scorer are unchanged.

**Spec:** [`docs/design/specs/2026-11-26-correcting-judge-design.md`](../specs/2026-11-26-correcting-judge-design.md), section "Subclass extraction schemas (X1)" and the phase table (phase 3).

## Owner decisions (2026-11-26) and what they change in the spec

The spec assumed the registry held labels for the corporate extension fields. It holds none, so the owner decided three questions before this plan was written:

1. **Narrowing drops only fields the Dojo marks `not_applicable` for the subclass** (registry `dojo_status`), not every unlabeled field.
   - Built from dev, calibration and pool labels, "drop every unlabeled field" would have cut 8–18 of 19 contract fields (`parties` for 8 subclasses) and 17 of 21 merger fields. It would also have stopped production from extracting them.
   - What is dropped today:
     - corporate `filing_number` on seven subclasses;
     - `jurisdiction` and `signatories` on `subsidiary_list`;
     - merger `intent`, `keywords` and `subject_matter` on every merger subclass.
   - `dojo_status` comes from the vendored Dojo field map, not from labels, so held-out labels cannot shape it.
2. **Extension adds only fields with dev, calibration or pool labels.**
   - Today that is none. The 31 corporate entity fields have no labels in any set.
   - Correspondence `content_topic` and `sentiment_label` are corpus label tasks (`dojo_status: label_task`), not extraction fields, so they are not added. The Dojo never scores them as extraction, and the vendored doctrine says the extractor does not emit them.
   - The extension path is built and tested now, so a corporate field joins the schema when it gets labels and the registry is rebuilt.
3. **Fallback:** the class schema is used when any of these holds:
   - the predicted subclass is missing, `unknown`, `other`, or not in the committed list;
   - `classification_confidence` is missing or below the class's `low` band (vendored `pipeline.config.get_confidence_thresholds(doc_class)["low"]`).

   The sorter reports no separate subclass confidence.

**As built (execution rulings, 2026-11-27):**

- **The drop rule is tighter than decision 1.** A not-applicable field is dropped only when no dev,
  calibration or pool label gives it a value. The interim overlay gives corporate `filing_number` real values
  on `board_resolution`, `officer_certificate` and `powers_of_attorney`, and the scorer counts a labeled
  value. The registry gained a per-field `valued_by_set` for this.
- **What is dropped:** `filing_number` on `bylaws`, `indenture` and `rights_instrument`; all three fields on
  `subsidiary_list`; and the three merger fields on every merger subclass.
- **Bylaws `filing_number`.** Its one value label is held-out, so it is still dropped, and that document
  scores the field as a miss. This is the cost of the held-out rule.
- **Where HF-023 hooks in.** It targets `_instantiate_specialist` and swaps the schema per specialist
  instance, instead of stacking on HF-009's `_run_chunked_extraction` and patching `_call_structured` on the
  classes. Hotfix marks are per attribute, and the sampling layer's native path bypasses a class wrapper.
- **Coverage.** All five classes are covered and tested, at the owner's request. Contract, correspondence and
  insurance subclasses get their own schema, which equals the class schema until a field is dropped or added
  (or `job.schema_guide` adds guide text).

Consequences for the spec's other bullets:

- **Scorer allow-list.** It gains nothing today. Every possible extension field (a corporate Dojo entity) is already allowed by `eval/extraction_scope._allowed_fields`, so no SHF is re-pinned. A test (Task 4) fails if a future added field is not scoreable, and that is when an SHF change is due.
- **Per-subclass descriptions.** These ride on `job.schema_guide`. The registry's per-field `guide` text replaces a kept or added field's description only when `job.schema_guide` is also on.

## Global Constraints

- No edits to `vendor/`. Pipeline behaviour changes through `src/mailroom_sandbox/vendor_hotfixes.py` (HF-023), with its row in `docs/vendor-hotfixes.md` and `docs/EXPERIMENT-CAMPAIGN-CONTRACT.md` in the same change.
- The field lists are a committed file hashed into the run lock and never rebuilt during a run. Held-out labels never shape a schema: the builder reads `labeled_by_set` keys `dev`, `calibration` and `pool` only (the split's spelling is `heldout`).
- The switch is `job.subclass_schemas`, valid only with `task: pipeline`. *As built (owner, 2026-11-27): always on for pipeline runs. Unset resolves on and an explicit `false` is refused. Other tasks leave it unset (an explicit `false` there is accepted and stays `false`), unhashed. A run locked with a recorded hotfix set before HF-023 is refused on resume until `--force` re-locks it; a lock from before the hotfix layer resumes with class schemas only through preflight with no checkpoint, or a direct run with no started work.*
- No paid or live runs by an agent. Every test is offline.
- Local checks: named test files with `-n 0 --no-cov`; full suite and coverage (`fail_under = 84`, never lowered) in hosted CircleCI.
- Never edit `_run_pipeline_doc_once` or `_pipeline_item` in `eval/runners.py` (pinned by SHF-012), or `eval/extraction_scope.applicable_expected_fields` (pinned by SHF-001 and SHF-015).
- New pages are indexed in `docs/README.md` (`tests/test_docs_drift.py`).

## Review Focus

1. **A dropped field that is still scored.** If the Dojo scored a `not_applicable` field, dropping it would turn a hit into a miss: a silent score drop (critical regression 1). Pinned by `test_a_dropped_field_never_changes_a_score` (Task 4). The drop rule reads only dev, calibration and pool labels, so a held-out value on a dropped field still scores as a miss (bylaws `filing_number`, above): a dropped field is score-neutral on the tuning sets, not on every split.
2. **A narrowed schema leaking past its extraction.** The judge, the arbiter or the next document must see the class schema. Pinned by `test_the_narrowed_schema_ends_with_its_extraction` (Task 3).
3. **A chunked document.** Every chunk window of a long document must get the same narrowed schema, and the chunk merge must still run. Pinned by `test_every_chunk_gets_the_narrowed_schema` (Task 3).
4. **The field list changing under a locked run.** Editing the committed file after preflight must stop the run, not run a different schema under the old hash. Pinned by `test_a_field_list_changed_after_the_lock_refuses_to_activate` (Task 3).
5. **A classifier with no confidence.** A missing `classification_confidence` must fall back, not narrow. Pinned by a case in `test_a_low_or_missing_confidence_falls_back` (Task 2).

---

### Task 1: The committed field list and its builder

**Files:**

- Create: `src/mailroom_sandbox/subclass_fields.py`
- Create: `scripts/build_subclass_fields.py` (writes the file; `--check` exits 1 when stale)
- Create: `config/extraction/subclass_extraction_fields.json` (generated by the script)
- Test: `tests/test_subclass_fields.py`

**Interfaces:**

- Produces:
  - `FIELDS_PATH: Path`, the committed file.
  - `SCHEMA_ID = "mailroom.subclass_extraction_fields/v1"`.
  - `build_field_lists(registry: Mapping[str, Any]) -> dict[str, Any]` returns:

    ```json
    {"schema": SCHEMA_ID,
     "registry_sha256": "<sha of subclass_schemas.json>",
     "classes": {"<class>": {"<subclass>": {
         "drop": ["<field>", ...],
         "add": {"<field>": {"type": "<registry type>"}},
         "guide": {"<field>": "<labeling-guide text>"}}}}}
    ```

    All lists are sorted and all keys emitted in sorted order, so the output is deterministic.
  - `load_field_lists(path: Path = FIELDS_PATH) -> dict[str, Any]`.
  - `field_lists_sha256(path: Path = FIELDS_PATH) -> str`, the sha256 of the file bytes.
- Rules:
  - **drop:** a field in the class's `output_schema_fields` whose subclass entry has `dojo_status == "not_applicable"`.
  - **add:** a field not in `output_schema_fields` with `dojo_status` not in (`not_applicable`, `label_task`, `pending_annotation`, `absent_from_dojo`), and with `labeled_by_set["dev"] + ["calibration"] + ["pool"] > 0`.
  - **guide:** the entry's `guide` string, for kept and added fields that have one.

- [x] **Step 1: Write the failing tests** in `tests/test_subclass_fields.py`, using the real committed registry unless noted:
  - `test_not_applicable_class_fields_are_dropped`:
    - `subsidiary_list` drop == `["filing_number", "jurisdiction", "signatories"]`;
    - merger `all_cash` drop == `["intent", "keywords", "subject_matter"]`;
    - contract `license` drop == `[]`.
  - `test_held_out_labels_do_not_change_the_lists`: deep-copy the registry, then set every `labeled_by_set["heldout"]` to 0 in one copy and to 999 in another. Both build output equal to the original's.
  - `test_a_labeled_extension_field_is_added`: a registry copy where corporate `bylaws` gains `certifying_officer` with `in_output_schema: false`, `dojo_status: "scored"`, `labeled_by_set: {"dev": 3, "calibration": 0, "pool": 0, "heldout": 0}` and `type: "name"`. Its `add` == `{"certifying_officer": {"type": "name"}}`.
  - `test_a_held_out_only_extension_field_is_not_added`: the same field with only `heldout: 5` is absent from `add`.
  - `test_label_task_fields_are_never_added`: no correspondence subclass has `content_topic` or `sentiment_label` in `add`.
  - `test_the_committed_field_lists_match_the_registry`: `load_field_lists() == build_field_lists(json.load(registry))`, and `registry_sha256` matches the registry file.
- [x] **Step 2: Run them.** `.venv/bin/python -m pytest -q tests/test_subclass_fields.py -n 0 --no-cov`. Expected: FAIL (module missing).
- [x] **Step 3: Implement `subclass_fields.py` and the script, then generate the file.** `python scripts/build_subclass_fields.py`.
- [x] **Step 4: Run them again.** Same command. Expected: all PASS. `python scripts/build_subclass_fields.py --check` exits 0.
- [x] **Step 5: Commit** `feat(subclass): committed subclass field lists from the label registry (phase3 task 1)`.

### Task 2: Schema selection

**Files:**

- Create: `src/mailroom_sandbox/subclass_extraction.py`
- Test: `tests/test_subclass_extraction.py`

**Interfaces:**

- Consumes: `load_field_lists` (Task 1).
- Produces:
  - `FALLBACK_SUBCLASSES = frozenset({"", "unknown", "other"})`.
  - `choose_schema(doc_class: str, subclass: str | None, confidence: float | None, base: dict, lists: Mapping[str, Any], *, low: float | None, guide: bool) -> tuple[dict, str]`.
    - It returns `(schema, reason)`, with `reason` one of `"subclass"`, `"fallback:unknown"` or `"fallback:low_confidence"`.
    - On fallback, `schema is base`.
    - It never mutates `base`. `base` is the vendored shape from `build_structured_schema`: `{"type", "title", "properties", "required", "additionalProperties"}`.
  - `low_band(doc_class: str) -> float | None`, which wraps the vendored `pipeline.config.get_confidence_thresholds(doc_class).get("low")`.
- Narrowed schema:
  - It is a deep copy of `base`.
  - Each `drop` field is removed from `properties` and `required`.
  - Each `add` field becomes `properties[f] = {"type": ["array", "null"], "items": {"type": "string"}}` when its registry type is `list` or ends in `_list`. Otherwise it is `{"type": ["string", "null"]}`. It is appended to `required` when `base["required"]` lists every base property; strict structured output needs that.
  - With `guide=True`, each kept or added field with guide text gets that text as its `description`.

- [x] **Step 1: Write the failing tests:**
  - `test_a_listed_subclass_gets_its_narrowed_schema`:
    - `corporate_record` / `subsidiary_list`, with confidence 0.99 and the real `SPECIALIST_SCHEMAS["corporate_record"]`;
    - `filing_number` is in neither `properties` nor `required`, and the reason is `"subclass"`;
    - the base still has `filing_number`.
  - `test_each_listed_subclass_schema_matches_the_committed_list`: for every (class, subclass) in the committed file, `set(properties) == set(base properties) - drop | add`.
  - `test_an_unknown_or_other_subclass_gets_the_class_schema`: parametrized over `None`, `""`, `"unknown"`, `"other"` and `"not_a_subclass"`. The result `is base` and the reason is `"fallback:unknown"`.
  - `test_a_low_or_missing_confidence_falls_back`, with `low=0.6`:
    - confidence `0.59` falls back (reason `"fallback:low_confidence"`);
    - `None` also falls back;
    - `0.6` gets `"subclass"`.
  - `test_an_added_field_is_requested`: synthetic lists with `add: {"certifying_officer": {"type": "name"}}` on `bylaws`. The field is in `properties` and in `required`.
  - `test_guide_text_replaces_descriptions_only_with_schema_guide`. With `guide=False`, descriptions equal the base's. With `guide=True`, a field with guide text carries it.
- [x] **Step 2: Run them.** `.venv/bin/python -m pytest -q tests/test_subclass_extraction.py -n 0 --no-cov`. Expected: FAIL.
- [x] **Step 3: Implement the module.**
- [x] **Step 4: Run them again.** Expected: PASS.
- [x] **Step 5: Commit** `feat(subclass): choose a subclass extraction schema with class fallback (phase3 task 2)`.

### Task 3: The switch, the lock and HF-023

**Files:**

- Modify:
  - `src/mailroom_sandbox/job/spec.py`: field next to `governor`; pipeline-only validator like `_governor_in_pipeline`; `spec_core` additions like the governor's at `spec_core` / `specialist_subclass_sha256`.
- Modify: `src/mailroom_sandbox/runtime.py`, with activation next to the governor's (`locked_job` block).
- Modify: `src/mailroom_sandbox/subclass_extraction.py`, adding the activation state and the wrappers.
- Modify: `src/mailroom_sandbox/vendor_hotfixes.py`, adding HF-023 to `HOTFIXES` after HF-019.
- Test: `tests/test_subclass_extraction.py`, `tests/test_job_spec.py` and `tests/test_vendor_hotfixes.py`.

**Interfaces:**

- Consumes: `choose_schema`, `low_band` (Task 2); `load_field_lists`, `field_lists_sha256` (Task 1).
- Produces:
  - `JobSpec.subclass_schemas: bool | None = None` (as built). `task: pipeline` resolves it to `True` on a copy of the job section and refuses an explicit `False`; other tasks leave it unset, and an explicit `False` there is accepted and kept. When true, `spec_core` adds `"subclass_schemas": True` and `"subclass_fields_sha256"`, so every pipeline `spec_hash` changes. Nothing is added when unset.
  - `subclass_extraction.activate(lists: Mapping[str, Any] | None = None, *, sha256: str, guide: bool) -> None` (as built). Without `lists` it reads the file once and hashes and parses the same bytes (`subclass_fields.read_field_lists`). It raises `RuntimeError` when the digest differs from `sha256`. An ad-hoc eval with no lock activates with the committed file.
  - `subclass_extraction.deactivate() -> None`.
  - `subclass_extraction.active() -> bool`.
  - HF-023. **As built** (superseding the four-wrapper list below, kept as the original design): the `_build_handoff_context` wrapper records the choice from the state (`record_choice`), and the `graph.build_graph._instantiate_specialist` wrapper binds it (`bind_choice`), giving that one specialist instance an instance-level `_call_structured` and `schema` carrying the narrowed schema. One instance serves one document's extraction and every chunk window, so nothing reaches the judge, the arbiter or the next document. The original design:
    1. `graph.build_graph._build_handoff_context(state)`: when active, it records the choice in a `ContextVar` (`_PENDING`) from `state["doc_type"]` (resolved with the vendored `resolve_extract_class`), the subclass and `state["classification_confidence"]`. The subclass is `state["contract_subtype"]` for `contract` and `state["doc_subclass"]` otherwise. The return value is unchanged.
    2. `graph.build_graph._run_chunked_extraction`, stacked over HF-009: it moves `_PENDING` into `_ACTIVE` for the duration of the call, resets `_ACTIVE` in `finally`, and clears `_PENDING`.
    3. `agents.base.BaseAgent._call_structured` (corporate, correspondence, insurance).
    4. `langchain_agents.base_agent.BaseAgent._call_structured` (contract, merger).

    Wrappers 3 and 4 replace `json_schema` with the active choice only when `json_schema is` the base schema object the choice was made from. Every other call is untouched.
  - Off (`active()` false), every wrapper passes straight through.

- [x] **Step 1: Write the failing tests:**
  - `test_subclass_schemas_is_off_by_default_and_unhashed` (test_job_spec): a pipeline spec without the key has the same `spec_hash` as before, and `spec_core` has no `subclass_` keys. *Superseded:* the switch is always on for pipeline runs, so a pipeline spec without the key now resolves on and its `spec_hash` changes; the test was replaced by the always-on and non-pipeline-unset tests.
  - `test_subclass_schemas_requires_a_pipeline_task` (test_job_spec): `subclass_schemas: true` on a non-pipeline task fails validation (`false` is accepted and kept).
  - `test_the_lock_changes_when_the_field_list_changes`: monkeypatch `FIELDS_PATH` to a temporary copy, then change one `drop` list. `spec_hash` differs.
  - `test_a_field_list_changed_after_the_lock_refuses_to_activate`: `activate(..., sha256="0"*64)` raises `RuntimeError`.
  - `test_an_extraction_requests_the_narrowed_schema`: parametrized over `corporate_record`/`subsidiary_list` (agents base) and `merger_agreement`/`all_cash` (langchain base).
    - Apply HF-023 and activate.
    - Stub the provider call under `_call_structured` to capture `json_schema`.
    - Drive `_build_handoff_context(state)` and then the vendored `_extract_<class>` with a short text.
    - The captured schema lacks the dropped fields.
  - `test_off_sends_the_class_schema_unchanged`: the same setup with the switch off. The captured schema `is SPECIALIST_SCHEMAS[cls]`.
  - `test_every_chunk_gets_the_narrowed_schema`: a document longer than one window (monkeypatch the chunk config to small windows). Every captured call uses the narrowed schema, and the merged result is returned.
  - `test_the_narrowed_schema_ends_with_its_extraction`: after the extraction returns, a `_call_structured` with the class schema (as the judge would make) is not replaced, and `_ACTIVE` is unset.
  - `test_hf023_is_registered_and_current` (test_vendor_hotfixes): HF-023 is in `HOTFIXES` and its targets are not stale.
- [x] **Step 2: Run them.**

  ```bash
  .venv/bin/python -m pytest -q tests/test_subclass_extraction.py tests/test_job_spec.py tests/test_vendor_hotfixes.py -n 0 --no-cov
  ```

  Expected: the new tests FAIL.
- [x] **Step 3: Implement the spec field, `spec_core`, runtime activation (deactivate when the locked job has it off) and HF-023.**
- [x] **Step 4: Run them again.** Same command. Expected: PASS. Then run `tests/test_runtime.py`, `tests/test_schema_guide.py` and `tests/test_scoring_hotfix_fingerprint.py`. Expected: PASS, with no SHF made stale.
- [x] **Step 5: Commit** `feat(subclass): job.subclass_schemas switch, lock hash and HF-023 (phase3 task 3)`.

### Task 4: Scoring guards and docs

**Files:**

- Test: `tests/test_subclass_extraction.py`
- Modify:
  - `docs/jobs.md`: a `job.subclass_schemas` section with the three rules, the fallback, the guide interaction and the lock hash;
  - `docs/vendor-hotfixes.md` and `docs/EXPERIMENT-CAMPAIGN-CONTRACT.md`: HF-023 rows;
  - `docs/critical-regressions.md`: rows 1 and 3, naming the guard tests;
  - `CHANGELOG.md`: Unreleased;
  - `docs/README.md`: an index row for this plan, if not added with it;
  - the doc that describes `config/extraction/subclass_schemas.json` (find it with `grep -rln subclass_schemas.json docs`): name the new derived file.

**Interfaces:**

- Consumes: the committed lists (Task 1) and `eval.scoring.score_extraction_row(doc_type, predicted, expected, doc_subclass=...)`.

- [x] **Step 1: Write the failing tests:**
  - `test_a_dropped_field_never_changes_a_score`: for every (class, subclass, field) in a committed `drop` list:
    - build `expected` with that field set to a non-empty value plus one kept field, and score two predictions with `score_extraction_row`: one with the field set to the same value, one without the field;
    - the headline score and the field events are equal.

    If this fails for a field, the builder must also keep any field the scorer counts. Record that as a ruling and add that condition to Task 1's drop rule.
  - `test_every_added_field_is_scoreable`: for every committed `add` field, `applicable_expected_fields(cls, {f: "x"})` keeps `f`. Also check the synthetic `bylaws`/`certifying_officer` case from Task 1.
  - `test_docs_name_hf023`: `docs/vendor-hotfixes.md` and `docs/EXPERIMENT-CAMPAIGN-CONTRACT.md` each mention `HF-023`, if the existing hotfix-doc test does not already enforce this. Check `tests/test_vendor_hotfixes.py` first and skip this test if it does.
- [x] **Step 2: Run them.**

  ```bash
  .venv/bin/python -m pytest -q tests/test_subclass_extraction.py -n 0 --no-cov
  ```

  Expected: the docs test FAILs. The scoring tests PASS if the Dojo skips `not_applicable` fields, as `extraction_schemas.py` documents; a pass there is a finding to record, not a skipped RED.
- [x] **Step 3: Write the docs.**
- [x] **Step 4: Run every touched test file.**

  ```bash
  .venv/bin/python -m pytest -q tests/test_subclass_fields.py tests/test_subclass_extraction.py tests/test_job_spec.py tests/test_vendor_hotfixes.py tests/test_runtime.py tests/test_schema_guide.py tests/test_scoring_hotfix_fingerprint.py tests/test_docs_drift.py tests/test_doc_paths.py -n 0 --no-cov
  ruff check src tests scripts
  ```

  Expected: PASS and clean.
- [x] **Step 5: Commit** `docs(subclass): document job.subclass_schemas and HF-023; scoring guards (phase3 task 4)`.

### Later owner decisions (2026-11-27) and open-PR alignment

- **Always on.** "Subclass-specific extraction schemas should always be used when they are available." `job.subclass_schemas` resolves on for every pipeline run, and an explicit `false` is refused.
- **All document types.** Narrowing also drops fields whose Dojo status is `absent_from_dojo` or `documented_absent` (the scorer never counts them as a value), on the same no-dev/calibration/pool-value condition. That adds contract `maud_clauses`/`merger_consideration` and insurance `cms_source_table`/`adjuster`/`denial_reasons` where absent. Corporate `filing_number` stays on the three subclasses whose interim labels carry values.
- **Open PRs.**
  - The hotfix is HF-023, because #425 registers HF-020 to HF-022 and #437 registers HF-021. Those two still collide with each other.
  - #425 composes its own corporate request schema on `CorporateRecordsSpecialist.extract`, and HF-023 leaves a corporate specialist with a hotfixed `extract` to it. #425's registry change, per-subclass `output_schema_fields`, is read by the field-list builder. Its rebuilt `subclass_schemas.json` must be regenerated together with this branch's `valued_by_set`, followed by `python scripts/build_subclass_fields.py`.
  - #437's `_build_handoff_context` wrapper stacks with HF-023's in either order (`test_hf023_stacks_with_another_handoff_wrapper`).
  - #436 only removes truth labels, which leave both sides of the score, so the drops stay score-neutral.

- **Review follow-ups (owner, 2026-11-27).**
  - A NaN or non-numeric confidence falls back to the class schema.
  - HF-023 pins `retry_extract_node`.
  - HF-024 shows the judge, the arbiter and the retry summary only the fields the extraction was asked for.
  - The `valued_by_set` comment in `subclass_schemas.py` is reworded.

## Risks and follow-ups

- **The extension is empty today.** It adds a field only once that field has labels. Labeling the corporate entity fields is the follow-up that makes it do anything.
- **Narrowing is small today:** 2–3 fields per subclass (contract, merger and insurance, and up to 3 for corporate). Most of the spec's token saving waits on labels or a later owner decision.
- **Unfinished runs.** HF-023 changes the locked hotfix set, so an unfinished run locked before this PR resumes only with `--force`, as in phase 2.
- **Upstream issue draft** (for the owner to file in llm-mailroom): "Extraction asks every subclass for the whole class schema, including fields the Dojo marks not applicable."
