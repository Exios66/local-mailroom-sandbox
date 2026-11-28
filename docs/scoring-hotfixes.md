# Scoring hotfixes

`src/mailroom_sandbox/scoring_hotfixes.py` corrects scoring defects the experiments cannot wait
for. The scorer is the vendored Dojo pin (`vendor/llm-dojo-scoring`, never edited) plus the
sandbox code that calls it. Each correction has an id (`SHF-NNN`) and is never silent.

## Rules

- **Bound to the code it corrects.** Each fix lists its targets (`module:qualname`) with the
  sha256 of the target's source as written in its module file, a reviewed data file it reads
  (`file:<repo path>` with the file's sha256), or a module constant that has no source text of its
  own, such as a regex or a token set (`value:<module>:<name>` with the sha256 of its value: sets
  and mappings sorted, a regex as pattern and flags, a function named, never printed). When a vendor
  refresh or an edit changes a target, the fix is `stale`: it is not applied, and `sandbox run preflight`
  fails on the `scoring_hotfixes` check until the fix is re-validated (update the sha after
  checking the fix still holds) or retired. Patching a function target at run time (for example
  `monkeypatch.setattr` in a test) does not change its fingerprint, which is read from the file; a
  `value:` target reads the live value, so patching a constant does.
- **Dual reported.** A scoring entrypoint scores each row with every fix off (the raw Dojo-pin
  value, under `raw_dojo`) and with the current fixes on (the headline).
  `scoring_hotfixes` names the fixes that were on; `scoring_hotfixes_changed` names the
  headline keys whose value differs. A report built on the headline also carries
  `headline_basis` (`{"headline": "hotfixed", "raw_key": "raw_dojo", "fixes_key":
  "scoring_hotfixes", ...}`), so a reader knows which number is which.
- **Recorded in every run lock** (`scoring_hotfixes`: the module sha256 and each fix's id and
  target fingerprints). A resume refuses a lock whose set differs, and the executing process
  (local or the Modal job worker) refuses to start when its set differs or a fix is not current.
- **Tracked upstream.** Each fix names where it belongs: an llm-dojo-scoring issue (D-N below,
  filed as [#188](https://github.com/Exios66/llm-dojo-scoring/issues/188) to
  [#192](https://github.com/Exios66/llm-dojo-scoring/issues/192)) or `sandbox` for a defect in this
  repository's scoring code.

Outside a `hotfixed()` block every per-row scoring-call fix (SHF-001 to SHF-004, SHF-010's raw
revert, SHF-015, SHF-019) is off, so a scorer that does not opt in gets the Dojo pin's behaviour unchanged.
The other fixes act outside a `hotfixed()` block and are on whenever they are current: the run
aggregation fixes (SHF-005, SHF-006, SHF-007, SHF-008, SHF-011), SHF-010 during truth preparation
(`gold_labels.apply_near_gold`), SHF-009 in the Decisions routing contract (`decision_backends`),
SHF-012 in subclass scoring, SHF-015's and SHF-019's label count in the gate (`job/gate.labelled_count`), and SHF-013 in the isolated sorter and
`sorter_reviewer` scoring (`eval/agents.py`, `eval/scoring.py`), in pipeline subclass scoring and in
`sorter_arms`. SHF-013 always
keeps the Hub-truth figures beside its own (`raw_dojo`, `hub_truth`), and its corrections file must
still match the pinned fingerprint when it is read, or scoring stops. SHF-009's `forced_choice` is the forced-choice
answer from the same question-set response, not a second request.

## Fixes

| Id | Layer | Correction | Upstream |
| --- | --- | --- | --- |
| SHF-001 | sandbox | A value predicted on a field the truth documents as absent (`gt_presence: schema_documented_absence`) is a false positive on every class, not only `corporate_record`, and counts as a hallucination. Re-validated at the Dojo `7d69bbd` refresh: `extraction_binary_metrics` now skips a contract's v1 parse-compat keys (`merger_consideration`, `maud_clauses`), which the sandbox's contract scope never restores, so the fix holds unchanged. | sandbox (`extraction_scope`); Dojo D-1 ([#188](https://github.com/Exios66/llm-dojo-scoring/issues/188)) |
| SHF-002 | dojo | A name whose tokens are a strict subset or superset of the truth's (after legal-suffix, "the", honorific and initial removal) is a partial match (token Jaccard), not an exact 1.0. | Dojo D-2 ([#189](https://github.com/Exios66/llm-dojo-scoring/issues/189)) |
| SHF-003 | dojo | Two amounts in different currencies do not match. A currency counts as stated by its ISO code, its symbol or its name in words (`euros`, `sterling`, `yen`, `US / Canadian / Australian dollars`; a bare `dollars` is USD only when nothing else is stated, as a bare `$` is; a bare `pounds` is not read). A `$` takes the currency of a prefix attached to it (`C$`, `HK$`, `US$`) or of a currency adjective right before it, with up to two spaces between (`US $5,000`, `Canadian $5,000`, `Hong Kong $5`); any other `$` is USD when nothing else is stated and adds nothing beside another stated currency. | Dojo D-3 ([#190](https://github.com/Exios66/llm-dojo-scoring/issues/190)) |
| SHF-004 | dojo | Identifiers equal once every non-alphanumeric character is removed match (`CLM12345` = `CLM-12345`). | Dojo D-4 ([#191](https://github.com/Exios66/llm-dojo-scoring/issues/191)) |
| SHF-005 | sandbox | A row that errored (timeout, parse failure, crash) scores 0 in the run headline instead of leaving the denominator: in isolated evals, in the job-runner sorter scores, and in a rescore's `scores.json`, where a failed item scores 0 on the headline keys (`rescore.HEADLINE_KEYS`) of its own first score, else of its truth class, else of the run. | sandbox |
| SHF-006 | sandbox | A row with no truth is left out of the run mean and counted (`n_no_truth`) instead of averaging in as 0, in isolated evals and the job-runner sorter scores. | sandbox |
| SHF-007 | sandbox | Class labels compare case-, hyphen- and whitespace-folded; a row without a truth class is unscored; an abstention is its own outcome (scored wrong, routed to review). The job-runner sorter scores (`job/runner._scored_pairs`) fold the same way. The gate's `is_wrong_class` stays exact on purpose: it judges the class a document was archived under, and `eval/archive_correctness` mirrors it. | sandbox |
| SHF-008 | sandbox | Judge, arbiter and boss rows without a truth verdict are unscored instead of 1.0; a judge parse failure scores 0 with `parse_error`. | sandbox |
| SHF-009 | sandbox | Question set 4.0.0's `document_form`, `abstain`, `subclass_gate` and `truncation_notice` keys are applied: an abstention parks the document and the forced-choice answer is kept under `forced_choice`. | sandbox (`decision_backends.decide`) |
| SHF-010 | sandbox | A near-gold label supersedes a conflicting interim gate gap fill (not an `original_header` fill); the replaced value is kept under `truth_overrides` and scored as raw. Precedence reads the interim overlay the row was prepared with; when that snapshot is not passed and the current overlay's fingerprint differs from the row's, nothing is superseded. | sandbox (owner decision, `data/labels/review/INTERIM_AUDIT.md` step 2) |
| SHF-011 | sandbox | A paired A/B report scores a failed document 0 instead of crediting its partial extraction, and counts failed documents per arm. | sandbox |
| SHF-012 | sandbox | Pipeline items record the final sorter or reviewer subclass and score it jointly with the class on the canonical subclass token, not the Dojo's class-blind raw-string match. | sandbox; Dojo D-5 ([#192](https://github.com/Exios66/llm-dojo-scoring/issues/192)) |
| SHF-013 | sandbox | Isolated `sorter` (`task: isolated`) and `sorter_reviewer` runs score the subclass jointly with the class on the canonical subclass token (`subclass_scored`, `subclass_match`, `subclass_by_class`); an abstention or a failed row is a wrong subclass. A reviewed correction in `data/labels/review/subclass_corrections.jsonl` (`verdict: correct`, matching class and Hub value) replaces the Hub subclass for subclass scoring here, for pipeline subclass scoring (the per-item `subclass_correct`, flagged `subclass_corrected`, and the run's `score_subclass`), for the pain-point subclass outcome, and for subclass and unit scoring in `sorter_arms` (H5); the Hub-truth figures stay under `raw_dojo` (`raw_dojo_subclass_correct` per pipeline item, `subclass_raw_dojo` on a pipeline run's `score_subclass` figures, `hub_truth` in `sorter_arms`) and `subclass_corrections_applied` counts the corrected documents. Extraction scoring and the gate's lowest-field diagnosis score a corrected document against its reviewed subclass (the subclass-specific field alignment and schema), named under `subclass_corrected`; the raw side keeps the Hub `expected_subclass`. The truth fields derived from the subclass (corporate `record_type` and `intent`, contract `cuad_family`, merger `merger_consideration`) follow the correction while they still hold the Hub subclass's value, named under `subclass_derived_truth`. | sandbox |
| SHF-014 | retired | Served the pain-point composites from a byte-identical copy of the Dojo's `pipeline/pain_points.py` until the vendored pin shipped it. Retired at the Dojo `7d69bbd` vendor refresh, after `tests/test_pain_points.py` found the vendored module byte-identical to the copy; the copy is deleted and the composites come from the Dojo ([guide](pain-point-composites.md#where-the-scoring-comes-from)). | llm-dojo-scoring #185 (shipped) |
| SHF-015 | sandbox | Hub labels the Dojo's label policy calls stale (`llm_dojo_scoring.schemas.label_policy.stale_hub_labels`: a heuristic `intent`; templated correspondence `subject_matter` and metadata `keywords`; templated corporate ones) are not truth on the headline: they are dropped from both the truth and the prediction, their presence becomes `pending_annotation`, and the row names them under `stale_hub_labels`. An overlay listing keeps a field only when the stale reason is `intent_heuristic`, because a reviewed intent leaves `intent_source` as `heuristic`. Any other stale value is dropped even when the overlay lists the field: on production slice 0100 the staged overlay lists `keywords` after stripping a mailbox path, and 28 of 30 correspondence values are still a topic tag plus a type token (`keywords_metadata`). A corporate subject that is exactly those two keywords joined by "of" (optional trailing period, either order) is dropped as well (`subject_matter_record_title`, `keywords_record_title`); the Dojo's exhibit-note mark does not catch it. On that same slice the corporate headline moves from 0.712 to 0.897 (14 of 14 rows) and correspondence from 0.484 to 0.544. Merger stays 0.246: its headline is MAUD accuracy, and the suite field score on the same answers is 0.835. A caller that passes no overlay provenance (`overlay_fields=None`) gets no drop. The gate does not count a dropped label toward `min_labelled`. | sandbox (the sandbox's scope seam strips `intent_source`, so the Dojo's own `drop_stale_hub_labels`, llm-dojo-scoring #164 / #171 / #94, never ran here) |
| SHF-016 | sandbox | A contract row whose `cuad_clause_labels` map names no category (an empty CUAD universe, so `cuad_presence_f1` is `None`) keeps the suite field headline instead of the `None` that left the row unscoreable: the reviewed interim / near-gold field labels merged at truth prep stand in where the Hub supplied none. The row is marked `cuad_unlabeled` and `scoring_hotfixes` names `SHF-016`; the raw side keeps the Dojo pin's `None`, so `overall_extraction_score` shows under `scoring_hotfixes_changed` for exactly these rows. A contract row with labeled CUAD categories is unchanged, and the merger MAUD replacement is untouched (a merger's suite F1 is 0 by construction, so the suite basis is not a stand-in there). The gate scores such a row as the headline does: it counts the row's field labels toward `min_labelled` (`gate.labelled_count`, through `gate.cuad_unlabeled`) and diagnoses a miss on the lowest field (`gate_causes.extraction_miss`), not as a CUAD miss. | sandbox |
| SHF-019 | sandbox | A correspondence `sender`, `recipient`, `additional_recipients` or `communication_date` whose truth is still the reviewed `original_header` label (`data/labels/review/interim_reviews.jsonl`), and that the document text does not show, is not truth on the headline: it is dropped from both the truth and the prediction, its presence becomes `pending_annotation`, and the row names it under `header_unseen`. The cleaned corpus text dropped the Enron email header that the interim overlay restored as truth, so the model cannot read these values. The text shows a field when any of its quoted header lines, the value after a header line's colon, or any item of the label value appears in `doc_text` (case, whitespace, periods and commas folded), so a value quoted in a reply or a signature stays scored. A near-gold or staged label that replaced the header value, an empty label, another class, and a caller that passes no `doc_id` or no (or empty) text get no drop. On the cached Hub v9.3 corpus with staged overlay `9.3.1-rc.9` it drops 1,470 cells on 709 of the 1,000 correspondence documents (of 1,795 header cells; [design](design/specs/2026-11-27-correspondence-header-truth-design.md)). The gate does not count a dropped label toward `min_labelled`, score a fix to it, or name it the lowest field. Retires when the pinned corpus revision writes the header lines back into `doc_text`, which already makes it a no-op document by document. | sandbox (corpus text without the email header; the restored-header release is the upstream fix) |

## Where the new and extended fixes apply

Each entry gives what the fix changes, the code paths that apply it, and how a run records it.

- **SHF-019** (new). Changes the correspondence extraction headline as described in the table.
  - Paths: `eval/scoring.score_extraction_row`, through every caller that passes the row's
    `doc_id` and `doc_text` (pipeline runs, `sandbox rescore`, `job/pair_report`, the gate's
    document score, `run_extract_eval` and the isolated `extract` scorer). Also
    `job/gate.labelled_count`, `job/gate._fix_accuracy` and `job/gate_causes._field_scores`, and
    through `_field_scores` the gold audit's candidate frame (`gold_audit.specialist_disagreements`).
  - Not applied, as for SHF-015: `scripts/extraction_gate.py` `_field_truth`, and the R02 scorer
    hand-check, whose replay (`agents._score_extract(stale_labels=False)` passes
    `drop_unseen_headers=False`) and case pool (`labelled_count(..., drop_unseen_headers=False)`)
    keep every field the truth names. `scripts/sand032/rescore.py` passes no `doc_id`, so SHF-019
    is off there too.
  - What its fingerprint covers: those four functions and the reviews file
    (`file:data/labels/review/interim_reviews.jsonl`). The file is read once, and its sha256 must
    equal the pin: an edited file raises instead of scoring new truth under the old fingerprint.
  - Recorded as: the row's `header_unseen` lists the dropped fields; `scoring_hotfixes` lists
    `SHF-019`, and `scoring_hotfixes_changed` names the keys it moved. The raw side (`raw_dojo`)
    still scores every header label, so a campaign that compares runs across this change compares
    raw to raw.
  - Gate verdicts can move, as with SHF-015. On the cached Hub rows with staged overlay
    `9.3.1-rc.9`, 709 correspondence documents have a lower `labelled` and none crosses below
    `min_labelled` 2. With the interim and near-gold overlays instead, 1,477 cells drop on the same
    709 documents and 6 documents (2 dev, 1 calibration, 3 held-out) cross below it. Each such
    status carries `labelled_raw` and `labelled_header_unseen` (the labels SHF-019 alone dropped),
    and the gate report counts the archived documents SHF-019 took below the bar under
    `unscorable_by_shf019` (per class and pooled; `gate.md` names it when not zero), apart from
    `unscorable_by_shf015`, which now counts before SHF-019's drop.
  - The Modal job worker bundles `interim_reviews.jsonl` (`deploy/modal_job.py`), as it bundles
    SHF-013's corrections; a test checks that every `file:` target is bundled.
  - Not changed: a perfect answer still scores 1.0 (the fix only removes cells), the other
    classes, and every correspondence field that is not one of the four header fields.
- **SHF-016** (new). Changes the extraction headline for the empty-universe contract rows.
  - Paths: every caller of `eval/scoring._score_extraction_row_once` — pipeline runs, rescore,
    pair reports, the gate's document score, `run_extract_eval` and the isolated `extract`
    scorer — through the row seam, like SHF-001.
  - Also the gate: `gate.labelled_count` counts the row's field labels toward `min_labelled`, and
    `gate_causes.extraction_miss` diagnoses its miss on fields (`gate.cuad_unlabeled` decides
    both). `dataset.task_gt_min_field_labels` draws such rows on that count.
  - What its fingerprint covers: the seam (`_score_extraction_row_once`), the Dojo readers
    that decide the row's labeled universe (`gt_categories`, `score_cuad`) and the three gate
    functions above. SHF-015 and SHF-019 re-pin `labelled_count` with no change to their drops. A vendor refresh or
    `SANDBOX_DOJO_SNAPSHOT` that changes one of them makes SHF-016 `stale` (not applied,
    preflight fails) instead of moving headlines while it reads `current`.
  - Recorded as: the row's `cuad_unlabeled` is `True` when the stand-in applied;
    `scoring_hotfixes` lists `SHF-016`, and `scoring_hotfixes_changed` includes
    `overall_extraction_score` for exactly the rows it moves. The row's own `raw_dojo` keeps
    the Dojo pin's `None`; what a run-level raw mean does with that depends on the path:
    - `run_extract_eval`'s run `raw_dojo` leaves the rows out (its `raw_dojo.n_scored` is lower
      than the headline's `n_scored` by exactly these rows).
    - An isolated eval's raw side (`eval/runners._isolated_headline`) is the pre-hotfix
      aggregate, where a row without truth averages in as 0, so these rows count as 0 there.
    - A rescore's `scores.json` `raw_dojo` averages the scored items' hotfixed values (it is
      the scored-only mean of SHF-005, not a fixes-off aggregate), so it includes them at
      their headline score.
  - Not changed: a contract row with labeled CUAD categories still scores the CUAD basis, and
    the merger MAUD replacement is untouched (a merger's suite F1 is 0 by construction, so the
    suite basis is not a stand-in there). The Hub's own field labels also score when it labels
    a scored field; only the missing CUAD universe needed the seam change.
- **SHF-015** (new). Changes the extraction headline as described in the table.
  - What its fingerprint covers: the sandbox seam (`applicable_expected_fields`,
    `score_extraction_row`, `job/gate.labelled_count`), the Dojo's `stale_hub_labels` and
    `drop_stale_hub_labels`, and everything `stale_hub_labels` calls: the helpers by source
    (`_fields`, `_class`, `_corporate_stale`, `_correspondence_stale`, `_keywords`,
    `is_templated_subject_matter`, `metadata_keyword_kind`, `_keyword_list`, `_norm_token`,
    `is_empty_value`, `parse_gt_fields`, `parse_json_container`) and the constants they read by value
    (`_CLASS_STALE`, `_TEMPLATE_MARK`, `_ID_KEYWORD`, `_CIK_KEYWORD`, `_TOPIC_KEYS`, `_TEMPLATE_FRAME`,
    `_SNAKE_TOKEN`, `_TIMESTAMP`, `_DATE_OR_TIME`, `_EMAIL`, `_MAILBOX_ID`, `_FOLDER_NAMES`,
    `_CONTENT_LIKE_FOLDERS`, `_COMMUNICATION_TYPES`, `_NULL_TOKENS`). A vendor refresh or a
    `SANDBOX_DOJO_SNAPSHOT` that changes any of them makes SHF-015 `stale` (not applied, preflight
    fails, an older run lock needs a re-lock), so the stale-label verdicts cannot move while the flag
    reads `current`. `tests/test_scoring_hotfix_fingerprint.py` walks the call graph of
    `stale_hub_labels` and fails when a function or constant it reaches is not a target, so a new
    helper added by a refresh is caught when the fix is re-validated. Not covered: a runtime
    monkeypatch of a function (the fingerprint of a function is its file source, as for every fix),
    and the Python standard library.
  - Paths: `eval/scoring.score_extraction_row`, used through `eval/runners._score_pipeline_extraction`
    by pipeline runs, `sandbox rescore`, `job/pair_report` and the gate's document score. Also
    `run_extract_eval` and the isolated `extract` scorer (`eval/agents._score_extract`), which
    pass the row's overlay markers.
  - Also: `job/gate.labelled_count`. Not applied in `scripts/extraction_gate.py` `_field_truth`
    (the extraction-gate calibration, known limit 4) or in the R02 scorer hand-check (limit 5).
  - Gate verdicts can move. A document's `labelled` no longer counts a dropped label, so one that
    had exactly `min_labelled` labels can become `unscorable_archive`. Each such document's
    gate status carries `labelled_raw` (the count before the drop; present only when it differs
    from `labelled`), and the gate report's `pooled.unscorable_by_shf015` and each class's
    `unscorable_by_shf015` count the archived documents SHF-015 alone made unscorable; the rendered
    `gate.md` names that count after the pooled line when it is not zero. Measured
    on the 3,302 cached Hub rows with the interim and near-gold overlays applied and
    `min_labelled` 2 (`mailroom_sandbox.job.gate.Bars` default): 678 documents have a different
    `labelled` (450 corporate_record, 150 insurance_claim, 78 correspondence) and 8
    corporate_record documents (450 to 442 scorable) cross below the bar. No document crosses
    above it, and no other class moves. At the per-class minimum of 20 scorable archives this
    changes no class's standing.
  - A row whose every scored label is stale has no score (`overall_extraction_score` is `None`; its
    raw Dojo-pin value is 0.0 and still counts under `raw_dojo`). `run_extract_eval`'s headline
    averages only the rows that have one, so it reports `n_scored` beside `n`: `n` counts the
    rows, `n_scored` the rows the mean averaged, and `raw_dojo.n_scored` the same on the raw side
    (a stale label still scores there). `n_scored` below `n` means rows left the denominator, as
    the scored n beside every metric of [critical regression 1](critical-regressions.md); it
    appears in `scoring_hotfixes_changed` when the two sides differ. `n_scored` is additive: `n`
    keeps its meaning.
  - A pipeline run's headline does the same for its two means: `extraction_overall_n_scored` and
    `extraction_overall_correct_class_n_scored` are the number of documents `extraction_overall`
    and `extraction_overall_correct_class` average (documents with a numeric
    `overall_extraction_score`, and for the second only those routed to their true class). A count
    is 0 when its mean is `None`. `raw_dojo` carries both counts over the raw rows, and a count
    that differs between the two sides appears in `scoring_hotfixes_changed`. Neither count is
    sent to Langfuse. A record written before the counts existed has neither key: read a missing
    count as unknown, not 0. A rescore's `scores.json` already reports `n` beside each per-item mean
    (`means.overall_extraction_score.n`, and `scored` for the items); a stale-only item has no
    headline score there and is not counted, while its own `raw_dojo` score stays on the item.
    So the raw counts differ for the same items. A rescore's run-level `raw_dojo` `n` leaves out
    a stale-only item, as its headline does, and also a failed item that SHF-005 zero-fills in the
    headline only (one ok and one failed item: headline `n` 2, `raw_dojo` `n` 1). A live run's
    `raw_dojo.extraction_overall_n_scored` counts a stale-only document (its raw score is a
    number). Compare raw counts only within one kind of run.
  - Not applied in `job/gate_causes._field_scores`: a heuristic `intent` must stay visible there
    for `label_suspect`.
  - Recorded as: the item record's `scoring_hotfixes` lists `SHF-015` and `raw_dojo` keeps the
    stale-label score. The item record's `stale_hub_labels` (`{field: reason}`, for example
    `{"intent": "intent_heuristic"}`) names each dropped field and why; the key is absent when
    nothing was dropped. `sandbox rescore` writes it the same way, because it builds items with
    `pipeline_item_score`. The extraction gate calibration reports `field_truth_hotfixes` (without
    SHF-015) and `shf015_scope`.
  - Known limits:
    1. Gate-cause typing (`job/gate_causes`) does not apply the SHF-015 drop, so `label_suspect`
       can still see a heuristic `intent`; a document failing on another field could be typed
       `label_suspect`. Follow-up.
    2. There is no near-gold refill after a drop. If a future overlay supplies a gap fill for a
       field whose Hub label is stale, the overlay skips it (the Hub field is populated) and
       SHF-015 then drops it. Today zero cached rows are affected.
    3. `scripts/sand032/rescore.py` passes no `overlay_fields`, so SHF-015 is off there by
       design and its output is not comparable to the hotfixed headline.
    4. The extraction-gate calibration (`scripts/extraction_gate.py calibrate`) does not apply
       SHF-015. The gate was asked about the question set's fields, `intent` among the key fields
       of corporate records and correspondence in `extraction_gate_v1.2.0`, and judged each, so the
       calibration keeps the Hub label as the field's truth: `key_truth`, the key-field set and
       the per-field entries match what the gate was asked, and the target is the one it was
       before SHF-015. Dropping a key field from the truth alone would score the gate's product of
       supports over fields the target no longer holds. The report's `shf015_scope` says so, and
       `stale_key_fields_kept["<class>:<field>"]` counts each stale key-field label that was
       kept (nothing is skipped for it). A calibration on the headline basis needs its own question set and a rerun of the
       gate.
    5. The R02 scorer hand-check (`scorer_handcheck.score_case`) scores the raw per-field basis,
       not the SHF-015 headline: it verifies the per-field scorer against hand-computed truth, and
       the committed sheet lists every field the truth names (a heuristic `intent` included).
       SHF-015 is a label-policy layer over the headline and is checked by its own tests.
    6. Compare like with like. A run scored before SHF-015 and one scored after differ on
       `corporate_record`, `correspondence` and `insurance_claim` headline extraction scores by
       construction (tables below). For a run that stores per-document answers (pipeline,
       isolated and paired runs), rescore it (`sandbox rescore`) on the current hotfixes before
       comparing its extraction headline across the SHF-015 boundary, or compare the per-item
       `raw_dojo` values each scored row records, which SHF-015 does not touch (a rescore's
       run-level `raw_dojo` section is not those values; see [rescore](rescore.md)).
       `extract`, `chained`, `local_vs_api` and
       `sorter_vs_modernbert` runs cannot be rescored (they keep only run-level scores; see
       [rescore](rescore.md)), and a `run_extract_eval` headline from before this change carries
       no `raw_dojo`. Their pre-SHF-015 extraction headlines are not comparable with later ones:
       rerun them instead.
- **SHF-013** (extended a third time). The truth fields derived from the subclass follow a reviewed
  correction on the headline. Before this, a corrected document kept its Hub subclass's derived
  values, so a specialist that read the record right was scored wrong on them. A field moves only
  while it still holds the Hub subclass's value (an overlay or review that set another value is kept):
  - corporate record: `record_type` and `intent`, by `scoring_hotfixes.CORPORATE_SUBCLASS_TRUTH`,
    the pair every Hub v9.3 corporate row carries for its subclass and the production prompt teaches
    (a test checks both);
  - contract: `cuad_family`, the corrected canonical token (`IP` to `Consulting Agreements` moves
    `ip` to `consulting`);
  - merger agreement: `merger_consideration`, the corrected token when it names a consideration,
    also filled when empty (as the label-repaired release does).
  - Paths: `eval/scoring.score_extraction_row` (`scoring_hotfixes.corrected_derived_truth`) and
    `job/gate_causes._field_scores`, with the same fingerprints as the subclass choice.
  - Recorded as: `subclass_derived_truth` on the row, `{field: [hub_value, corrected_value]}`. The
    raw side keeps the Hub values.
  - Measured on the cached Hub rows with staged overlay `9.3.1-rc.9`: 40 corporate `record_type`
    and 42 `intent` values move (an `intent` that SHF-015 drops as heuristic is not scored either
    way), 9 contract `cuad_family` values and 1 merger `merger_consideration`. An answer that reads
    the corrected record right scores 1.000 on the 42 corporate documents' headline, against 0.753
    on the raw side.
- **SHF-013** (extended again). The reviewed subclass corrections also choose the subclass an
  extraction is scored on:
  - Paths: `eval/scoring.score_extraction_row` (with `doc_id`; the isolated extract, pipeline and
    agent scorers pass the row's `id`) and `job/gate_causes._field_scores`. A caller's
    `doc_subclass` still takes precedence. Any subclass-scoped extraction scoring that reads
    `expected_subclass` downstream of `score_extraction_row` sees the corrected value on the
    headline only.
  - What its fingerprint covers: both seams are SHF-013 targets, beside the corrections file.
  - Recorded as: `subclass_corrected` on the row, and `scoring_hotfixes` lists `SHF-013` when a
    correction bound. The raw side scores the Hub subclass, so a moved headline shows under
    `scoring_hotfixes_changed`.
- **SHF-013** (extended). The reviewed subclass corrections also bind in pipeline scoring:
  - Paths: `eval/scoring.subclass_correct` and `score_subclass` (with `doc_ids`), called from
    `pipeline_item_score`, `run_pipeline_eval` and the pain-point subclass outcome.
  - Recorded as: `subclass_corrected` on the item and `subclass_corrections_applied` on the run.
    `scoring_hotfixes` lists `SHF-013`. The Hub-truth outcome stays under
    `raw_dojo_subclass_correct` on the item and `subclass_raw_dojo` on the run's
    `score_subclass` figures.
- **SHF-010** (extended). `run_extract_eval` now passes each row's `truth_overrides`, so the raw
  side scores the interim value near-gold replaced.
  - Recorded as: the run's scores carry `raw_dojo`, `scoring_hotfixes`,
    `scoring_hotfixes_changed` and `headline_basis`.
- **SHF-005** (extended). `rescore.run_scores` keeps failed items in the headline means of
  `scores.json`.
  - Recorded as: the scored-only means sit under `raw_dojo`, with `failed`,
    `failed_scored_zero`, `scoring_hotfixes` (`["SHF-005"]` when a failure was zero-filled),
    `scoring_hotfixes_changed` and `headline_basis`. That run-level `raw_dojo` aggregates the
    same top-level per-item scores the headline uses, not the per-row fixes-off values each
    scored item records under its own `raw_dojo` key (the rescore guide says so).
- **SHF-006 / SHF-007** (extended). `job/runner._scored_pairs`, the per-item job runner's sorter
  scores, folds labels and leaves blank-truth rows out.
  - Coupling: both fixes define the no-truth drop for these scores, so the drop is on when
    either is current; only SHF-007 folds the labels. With SHF-006 current and SHF-007 stale a
    blank-truth row is still left out and counted, and labels compare exactly. A row left out is
    named under both fixes that are current (`SHF-006`, `SHF-007`); folding alone names `SHF-007`.
  - Recorded as: `n_no_truth` and `n_errored_scored_wrong`. `scoring_hotfixes` lists each fix
    that moved the score, and the exact-match scores stay under `raw_dojo`.
- **SHF-002 / SHF-003 / SHF-004** (extended paths). `job/gate_causes._field_scores`, and with it
  `gold_audit.specialist_disagreements`, now score under `hotfixed()`, as does
  `scripts/extraction_gate.py` `_field_truth`. A field the headline scores right (a `CLM12345`
  for `CLM-12345`) is then never typed as the extraction miss. SHF-003 also reads currencies
  named in words. A bare "dollar(s)" is USD only when no other dollar currency is named: Canadian,
  Australian, Hong Kong, New Zealand and Singapore dollars (also `CA`, `AU`, `HK`, `NZ`, `SG`
  dollars, and the name after the word, "1,000 dollars Canadian") read as their own currency.
  Another dollar (Taiwan, Jamaican and so on) is still read as USD. Measured on the 3,302 cached
  Hub rows with both overlays applied: 98,872 truth strings, one containing "dollar", none read
  differently than before.
  - How a `$` is read: it takes the currency of a prefix attached to it (`US$`, `C$`, `A$`, `S$`,
    `CA$`, `AU$`, `HK$`, `NZ$`) or of a whole currency adjective right before it, with up to two
    spaces between (`US $5,000`, `U.S. $5`, `Canadian $5,000`, `Australian $5`, `Hong Kong $5`,
    `New Zealand $5`, `Singapore $5`). A single letter or a state code before a spaced sign is not
    a currency (`Plan A $5,000`, `San Jose, CA $5,000` are USD). Any other `$` reads as USD when the
    string states no other currency, and adds nothing beside one (`CAD $1,000` and `$1,000 CAD`
    are CAD). So `US $5,000 (C$6,800)` states USD and CAD, and still matches `$5,000`. The check
    only lowers: an amount the Dojo scored below 1.0 is never raised, and a real mismatch
    (`C$5,000` against `US$5,000`) still scores 0.0 when the Dojo called the amounts equal.
    Re-measured on the same 98,872 truth strings: none read differently than before.
  - Known limits:
    1. An adjective after the amount (`$5,000 Canadian`, `$5,000 (Canadian)`) is not read, so the
       `$` reads as USD.
    2. A `$` beside another stated currency adds nothing, so `$1,000 (approx. EUR 900)` states
       EUR only and does not match `$1,000`.
    3. When the Dojo cannot parse an amount numerically (`US $5,000 (C$6,800)`, `US$1,000`), it
       falls back to its fuzzy name match, and under SHF-002 that match scores a token subset or
       superset as a partial match. A correct multi-currency amount can therefore still score
       below 1.0 on the hotfixed headline (`US $5,000 (C$6,800)` against `$5,000` scores 0.3333
       with SHF-002 on and 1.0 with only SHF-003 on) although SHF-003 reads its currencies right.
       SHF-003 does not cause that score; whether SHF-002 should apply inside the money fallback
       is open.
  - Recorded as: the gate report and the calibration report name the fixes in force.
- **Per-item and report provenance.**
  - `pipeline_item_score` adds `raw_dojo` (the item's raw extraction values) and
    `scoring_hotfixes` to every item score.
  - `gate_report` adds `headline_basis` and `scoring_hotfixes` (the fixes in force when it
    scored).
  - The autoresearch ledger's metrics add `headline_basis`.

**Locks.** Every change above edits `scoring_hotfixes.py` or a fix target, so `module_sha256`
and the target fingerprints change. A new run's preflight locks the new set automatically
(`tests/test_scoring_golden.py::test_a_fresh_lock_and_its_outputs_carry_the_current_hotfix_set`).
A run locked before the change no longer matches: preflight refuses to resume it and the job
worker refuses to execute it, so it would need `sandbox run preflight --config CONFIG --run-id RUN --force` to re-lock (no run needs that today).

### SHF-015 on the pulled corpus

These figures were measured offline over the 3,302 cached Hub rows at the current pin, with the
interim overlay and then near-gold applied. They come from synthetic predictors, not model runs.
`copy` predicts the prepared truth. `stale-wrong` predicts the truth with every dropped field
replaced. "Before" is the hotfixed headline without SHF-015; "after" is with it. The table gives
the mean `overall_extraction_score`.

| Class | n | copy before | copy after | stale-wrong before | stale-wrong after | rows moved |
| --- | --- | --- | --- | --- | --- | --- |
| contract | 509 | 0.0491 | 0.0491 | 0.0491 | 0.0491 | 0 |
| corporate_record | 450 | 1.0 | 1.0 | 0.8774 | 1.0 | 395 |
| correspondence | 1,000 | 1.0 | 1.0 | 0.7525 | 1.0 | 904 |
| insurance_claim | 1,100 | 1.0 | 1.0 | 0.9902 | 1.0 | 150 |
| merger_agreement | 152 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |

`n` counts the rows that carry a score; every column averages the same rows, so the
before/after means stay paired. The per-class `n` values sum to 3,211, not 3,302: the 91
missing contract rows are in no column, because their CUAD label map labels no category, so the
contract headline returned no score for them when this table was measured, with SHF-015 off or
on (the same rows carry the heuristic `material_agreement` intent the policy would drop). Every
other class's `n` equals its corpus size. SHF-016 scores these rows on the suite basis from
the reviewed field labels that stand in for the missing CUAD universe. Only 30 of the 91 carried
such a label when SHF-016 landed; the near-gold contract labels added for the other 61 (agent
passes plus an Opus review, `use_as_truth: false`, not human gold) now cover all 91. This table
predates both: its `n` of 509 is from the measurement above. A rerun with SHF-016 current and
the labels in place has `n` 600 for contract (509 + 91), and the per-class `n` values then sum
to 3,302, the corpus size. Seven fields on the 21 documents reviewed in place (six
`party_roles`, one `payment_terms`) have no label record, so those documents score on their other fields only.

A prediction that equals the truth never moves. No merger_agreement row in the pinned corpus
carries a stale label, and a contract's heuristic `intent` (91 drops) is not a scored contract
field, so contract and merger scores do not move; the `copy` predictor does not emit the CUAD and
MAUD labels those two classes are scored on, so its scores there are low. The policy does not
exempt them: a merger_agreement's `intent` is a scored field, so a corpus revision with
heuristic merger intents would move merger scores.

Dropped labels, by field:

| Field | Count |
| --- | --- |
| correspondence `keywords` (`keywords_metadata`) | 904 |
| correspondence `subject_matter` (`subject_matter_templated`) | 904 |
| corporate_record `intent` (`intent_heuristic`) | 450 |
| insurance_claim `intent` | 150 |
| contract `intent` | 91 (not a scored contract field) |
| correspondence `intent` | 78 |

A further 27 correspondence intents are stale by policy but kept, because an interim correction
supplied them. No corporate `subject_matter` or `keywords` label is stale at this pin. No money
truth names its currency in words, so the SHF-003 change moves no current label.

## Truth evidence check

The truth the fixes score against is checked too. `mailroom_sandbox.notebook.label_overlay_grounding`
reads every populated truth label of the near-gold overlay (`data/labels/gold-overlay/`, which
SHF-010 lets supersede interim gap fills) and the interim overlay (`data/labels/interim/`), and
checks each one by the rule that admitted it:

| Label | Rule |
| --- | --- |
| A stored quote | The label gate's value rules (`gold_labels.evidence_support`): a whole date in one quote, money by value, token coverage for names and free text, the closed-label vocabulary and the per-field rules. The quote-length caps are not applied: a long `To:` header line is still evidence. |
| Reviewed (`review`) | The review file's rule (`interim_labels`): header lines for `original_header`, the record quote for `review_read_record`, the vocabulary alone for a reviewed intent (an optional quote is not held to the gate's minimum). |
| `derived` | Recomputed from the record's own `doc_subclass`. |
| A closed label with no quote | The value is in the field's vocabulary (`in_vocabulary`). |
| A gap fill or CUAD correction with no quote | The build's rule, against the document's Hub row when one is supplied (`rows`, bound by `doc_sha256`): every token in the text, or agreement with the row's CUAD spans. A gap fill whose stored support is under the admission threshold is `ungrounded` first, with or without the row. Otherwise `no_evidence`. |

Interim `disputed` labels are not truth and are not checked. `tests/test_notebook.py` fails on any
unsupported label. Pytest never reads `data/cache`, so in CI the 803 interim gap fills and CUAD
corrections stay `no_evidence`. Notebook 02 passes `cached_doc_rows()`: after
`sandbox datasets pull` it checks those against their documents as well, and asserts none fails.
At the current pin every truth label passes (gold-overlay 3270 supported, 876 in vocabulary;
interim 3651 supported, 55 in vocabulary).

## Merged truth and precedence

A run's truth is the Hub label, then the interim truth label, then near-gold, each filling only
fields the layers before it leave unlabelled; an interim correction replaces the Hub value it names,
and SHF-010 lets reviewed near-gold replace a conflicting interim gate gap fill (never a reviewed
`original_header` fill). `mailroom_sandbox.notebook.merged_truth` runs that merge
(`interim_labels.apply_overlay`, then `gold_labels.apply_near_gold`) over Hub rows and returns, per
scored field, the layer it came from (`breakdown()`), every document and field both overlays label
with whether they agree and which layer won (`overlaps`), and any result the precedence forbids
(`violations`). `tests/test_notebook.py` covers each source, each overlap outcome and a leaked
overlay; notebook 02 runs it over the pulled Hub corpus and asserts no violation.

At the current pin (3,302 documents) the Hub labels 68,702 fields, of which interim corrections replace 55, and the overlays fill 10,710 more:

| Class | Hub | Interim | Interim correction | Near-gold | Near-gold (SHF-010) |
| --- | --- | --- | --- | --- | --- |
| contract | 12,799 | 45 | 0 | 900 | 0 |
| corporate_record | 5,457 | 980 | 0 | 826 | 36 |
| correspondence | 20,795 | 2,365 | 55 | 4,925 | 4 |
| insurance_claim | 26,100 | 536 | 0 | 0 | 0 |
| merger_agreement | 3,496 | 93 | 0 | 0 | 0 |

The two overlays overlap on 2,450 document fields: 647 agree; 40 interim gate fills differ and
near-gold wins (SHF-010); 1,763 reviewed `original_header` fills differ and win. In 1,692 of those
near-gold read the field as absent, because the corpus text lost the email header the fill quotes;
in the other 71 it read a sign-off or the person a reply addresses. The header value is right, but
the model sees only the text, so those correspondence `sender` / `recipient` /
`additional_recipients` / `communication_date` fields are scored in `raw_dojo` against values not
in its input. On the headline, SHF-019 leaves a field whose header the text does not show out of
truth and prediction and names it under `header_unseen`, until the dataset restores the headers.
No precedence violation.

Hub labels are not all right, so a conflict with one is evaluated, and the clear winner is the
truth. An overlay replaces a Hub value only as an interim `correction`: a reviewed read of the
message (`review_read_message`, 55 intents) or the Hub's own CUAD evidence (`cuad_party_spans`,
`cuad_agreement_date`, 45 contract fields). A gate extraction that merely disagrees is `disputed`:
it is not truth, the Hub value stands, and `merged_truth(...).hub_conflicts` lists it with both
values and whether the text holds each, for review. At the current pin there are 30: 17
correspondence intents, where the text cannot settle a class and a review read is needed, and 13
contract or merger fields whose Hub truth the Dojo derives from CUAD spans (bare party names where
the gate adds descriptors, renewal clauses CUAD does not tag as a Renewal Term, clause lists, one
merger consideration). Settling one goes through a review file (`data/labels/interim/README.md`),
which makes the winner a `correction` and records who decided it.

## Upstream Dojo issues

- **D-1** ([llm-dojo-scoring#188](https://github.com/Exios66/llm-dojo-scoring/issues/188)) `extraction_binary_metrics` treats a documented-absent field as a hallucination only
  for `corporate_record`.
- **D-2** ([llm-dojo-scoring#189](https://github.com/Exios66/llm-dojo-scoring/issues/189)) `score_name_field` scores a token subset or superset of the truth name as an exact match.
- **D-3** ([llm-dojo-scoring#190](https://github.com/Exios66/llm-dojo-scoring/issues/190)) `score_money_field` ignores the currency.
- **D-4** ([llm-dojo-scoring#191](https://github.com/Exios66/llm-dojo-scoring/issues/191)) `score_id_field` does not normalize separators.
- **D-5** ([llm-dojo-scoring#192](https://github.com/Exios66/llm-dojo-scoring/issues/192)) `pipeline_subclass_match` compares raw subclass strings and ignores the class.

When the Dojo pin ships a fix, retire the matching
`SHF` entry in the same change that refreshes `vendor/llm-dojo-scoring`.
