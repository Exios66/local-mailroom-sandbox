# Mailroom Dataset v9.3: label-repaired CSV release

A partially labeled CSV release of
[`Lucius-Morningstar/mailroom-dataset`](https://huggingface.co/datasets/Lucius-Morningstar/mailroom-dataset)
**v9.3** (Hub revision `ff4ca546d4346991628c2616ae014afc15e9fe04`). It covers 3,302 business and
legal documents in five classes. Coverage is **87.9%** of per-class target fields (44,138 labeled,
6,094 unlabeled, 1 disputed/unresolved)—not a complete labeling. It is one snapshot of a dataset
that is still being developed, not the final release.

The published v9.3 ground truth labels 24,812 of the 50,233 per-class target fields (49.4%). This
release labels **44,138 (87.9%)**. Each added or changed label was chosen by a consensus vote over
every label source in this repository, and the vote that chose it is kept in the provenance file.

These flat per-class counters are not scored-field coverage. They include documented absences,
and since 2026-11-28 each corporate document's subclass fields (below). The 2026-11-26 scope correction withdraws
38 recent corporate annotations outside their subclass's applicable fields; four correspondence
absences remain for hallucination checks and are not new populated extraction targets. Raw
submissions and the preservation audit remain in
[`repair-artifacts`](../../../data/labels/repair-artifacts/v93-20261126-scope-correction/README.md).
New corporate collection must follow the registered subclass schema and source evidence.

## Files

| File | Rows | Contents |
| --- | ---: | --- |
| `mailroom_dataset_v9.3_label_repaired.csv` | 3,302 | One row per document: identifiers, metadata, text statistics, a 280-character text preview, every label field, and per-row completeness counters. **The main analysis file.** |
| `mailroom_dataset_v9.3_label_repaired_label_provenance.csv` | 50,299 | One row per document and target field (plus the 66 subclass changes): the chosen value, its presence code, the winning source, every source's vote, the agreement and the evidence quote. |
| `mailroom_dataset_v9.3_label_repaired_field_completeness.csv` | 104 | Per class and field: how many documents are labeled in v9.3 and here, populated or documented absent, still unlabeled, disputed, and conflicts resolved. |
| `mailroom_dataset_v9.3_label_repaired_summary.json` | N/A | Totals, source weights, and the sha256 of every input file. |
| `build_label_repaired.py` | N/A | The deterministic builder that wrote all of the above. |
| `mailroom_dataset_v9.3_label_repaired_text.csv.gz` | 3,302 | Full document text (`document_id`, `doc_text`), about 26 MB. **Not committed.** Run the builder with `--with-text` to create it. |

Paths below are relative to this release directory.

```python
import pandas as pd, json

df = pd.read_csv("mailroom_dataset_v9.3_label_repaired.csv")
prov = pd.read_csv("mailroom_dataset_v9.3_label_repaired_label_provenance.csv")
# list-valued cells (parties, keywords, signatories, ...) are JSON strings
df["parties_list"] = df["parties"].dropna().map(json.loads)
```

Optional full text (only after rebuilding with `--with-text`; the archive is not committed):

```python
text = pd.read_csv("mailroom_dataset_v9.3_label_repaired_text.csv.gz")
df = df.merge(text, on="document_id", how="left")
```

## Composition

| Class | Documents | Fields per document | Labeled in v9.3 | Labeled here |
| --- | ---: | ---: | ---: | ---: |
| `insurance_claim` | 1,100 | 17 | 94.1% | 100.0% |
| `correspondence` | 1,000 | 13 | 38.5% | 100.0% |
| `contract` | 600 | 17 | 0.0% | 66.7% |
| `corporate_record` | 450 | 9 + subclass | 39.5% | 77.6% |
| `merger_agreement` | 152 | 18 | 0.0% | 44.6% |

The target fields of each class are the fields of the class's extraction schema in the vendored
`llm-dojo-scoring`, leaving out the fields the schema marks `not_applicable`. Insurance
`claim_checklist` is left out as well: it is not used in the experiments or in production, and no
source labels it. Corporate `filing_number` is kept as an extra field. A field that belongs to another class is left blank.

A corporate document is also targeted on the salient fields of its subclass in the label registry
(`config/extraction/subclass_schemas.json`): an indenture on `trustee`, `guarantors`,
`securities_series`, `principal_amount` and `maturity_date`, a bylaws document on
`certifying_officer` and `last_amended_date`, and so on. The subclass is the Hub's, or a reviewed
correction's. The Hub labels none of these fields; the near-gold catalog does, and without a target
cell its labels never reached this release or the staged overlay production scores against (rc.10
carried none). The 1,013 subclass cells no source labels yet are counted as unlabeled.

## Label sources and the consensus vote

Each source that labels a (document, field) pair casts one vote. Its weight depends on how much
review stands behind it:

| Source | Weight | What it is |
| --- | ---: | --- |
| `owner_review` | final | The dataset owner's own review-desk decisions (`data/labels/review/human_reviews.jsonl`). Never outvoted. |
| `interim_reviewed` | 3 | Reviewed interim labels: correspondence intent corrections read from the message, sender/recipient/date read from the original Enron email header, corporate entity-name corrections. |
| `subclass_review` | 3 | Reviewed subclass corrections (`subclass_corrections.jsonl`). |
| `interim_correction` | 3 | Hub contract dates and parties corrected against the Hub's own CUAD evidence. |
| `near_gold_reviewed` | 3 | Gold-catalog labels a reviewing model accepted or corrected (`data/labels/gold-overlay/`). |
| `near_gold_two_pass` | 2 | Gold-catalog labels on which two independent labeling passes agreed. |
| `hub_v9.3` | 2 | The published v9.3 ground truth. |
| `interim_derived` | 2 | Labels computed from the Hub subclass, with no model involved. |
| `generated_derived` | 2 | **Generated by this build:** the Hub's own CUAD clause spans, MAUD answers and subclass converted into schema fields by the vendored Dojo rules (`document_name`, `parties`, `effective_date`, `agreement_date`, `governing_law`, `term_length`, `renewal_terms`, `cuad_clauses`, `cuad_family`, `maud_clauses`, `merger_consideration`, `communication_type`, `cms_source_table`). |
| `interim_gate` | 1.5 | Extractions an evaluation gate accepted, with every token found in the document. |
| `cuad_span` | 1.5 | **Generated by this build:** a CUAD annotator's clause span that answers a field the Dojo schema still marks pending. `expiration_date` is the end date stated in the *Expiration Date* span. CUAD casts no ballot when the span has no parseable calendar date, is start-only, or has ambiguous end dates; another source may still supply the date. `termination_notice_period` is the notice phrase in the *Notice Period To Terminate Renewal* and *Termination For Convenience* spans. `dispute_forum` is the named court or arbitral seat inside a *Governing Law* span. The span is in `evidence`. |
| `gold_candidate` | 1 | Gold-labeler output that passed automated checks but has not been reviewed. |
| `generated_rule` | 1 | **Generated by this build:** pattern extractions that quote verbatim document text (merger parties, acquirer, target, merger sub, dates, governing law, fees, exchange ratio, per-share cash, advisors, counsel; `/s/` signatories; corporate jurisdiction; contract agreement date and governing law where CUAD is silent). The quote is in `evidence`. |
| `gold_disputed`, `interim_disputed` | 0.5 | Values an automated check disputed. On their own they are **not** accepted: the cell is left blank with presence `disputed_unresolved`. |

Values are compared field by field: tokens are normalized, lists are compared as unordered sets,
dates in ISO form, "State of Ohio" equals "Ohio", and defined terms such as `("Seller")` are ignored
in names. Every empty value counts as one candidate, "documented absence". The candidate with the
most total weight wins, and a tie goes to the better-reviewed source. A reviewed or near-gold
label (`interim_reviewed`, `subclass_review`, `interim_correction`, `near_gold_reviewed`,
`near_gold_two_pass`) is truth over the Hub: when one votes, the Hub and the sources computed from
it (`hub_v9.3`, `interim_derived`, `generated_derived`) count for nothing (`rule:
reviewed_over_hub`). An echo of the Hub never outvotes a label read and checked against the
document, nor tips a contest between reviewed labels. Independent evidence (`cuad_span`,
`generated_rule`, `interim_gate`) still counts. The summary's `values_moved_by_reviewed_precedence`
counts the cells where the plain weighted vote would have chosen another value; on this build it is
empty (every such conflict was already won by the reviewed label), and the rule marks 2,047 cells. A short `cuad_span` phrase
that a longer label contains (the same numbers and most of the same words) counts as a vote for
that label, and the label keeps its fuller wording. `agreement` records
`unanimous`, `single_source` or `k-of-n`, and `weight_share` records the winner's share of the
weight. Two kinds of vote are flagged `needs_human`, which queues them for review without
changing the value:

- three or more competing values whose winner holds under half of the weight (none occurred);
- under `reviewed_over_hub`, a reviewed absence that overrides a populated value, or independent
  evidence that beats a reviewed label (22 cells, all reviewed absences).

With the 1 disputed cell, 23 cells need a human. A 2026-11-28 administrative review by two
independent reviewers read all 23 held absences: both kept 22 as absent (their concurrence is
recorded for the owner's sign-off; the cells stay queued) and both found one, an indenture's
governing-law `jurisdiction`, stated in the text (see
[the review archive](../../../data/labels/repair-artifacts/v93-20261128-held-absence-fable-review/README.md)). The 2026-11-28 executive vote settled 77 of
the 78 earlier disputed contract cells (see
[the vote archive](../../../data/labels/repair-artifacts/v93-20261128-contract-dispute-fable-votes/README.md));
the one left is a party name the source text prints with broken spacing.

**Check against production truth (unverified in this README).** A prior local rebuild reported that
the repository's scoring merge (`interim_labels.apply_overlay` then `gold_labels.apply_near_gold`)
labeled 35,140 of these cells and that the vote matched all 35,140, with 8,290 added cells from
generated labels (6,900), CUAD spans (584), unreviewed gold candidates (802), and 4 disputed gold
values a CUAD span confirms. Re-run the builder and compare against a dated validation artifact
before citing these totals; they are not pinned here.

**Check of the CUAD span mapping (unverified in this README).** The same local rebuild reported
agreement on 169 of 171 `expiration_date` cells, 43 of 46 `termination_notice_period` cells and
10 of 10 `dispute_forum` cells where a CUAD-mapped value overlapped a two-pass or gold label. CUAD
does not annotate party roles, so `party_roles` is not mapped from it. Treat these counts as
unverified until a dated rebuild records them in `summary.json` / provenance.

**Earlier rc.10 regeneration** (builder commit `736fe3ee`). Two independent changes moved
651 provenance cells against its previous committed outputs; no cell won by a reviewed, near-gold, interim-reviewed, owner or
Hub source changed value or presence:

- **Near-gold contract labels** (542 cells, all in the 61 empty-CUAD contracts that had no
  near-gold record; `tests/fixtures/empty_cuad_contract_ids.txt` lists all 91 empty-CUAD rows): 324 previously unlabeled cells, 182 unreviewed
  gold candidates promoted to `near_gold_reviewed`, and 36 `generated_rule` cells replaced by
  near-gold.
- **Event-defined dates are no longer absences** (109 cells in 91 other contracts): the builder
  fix that skips a ballot for a CUAD date span with no calendar date ("the date of the last
  signature") was committed without regenerating these files. 93 `effective_date` /
  `agreement_date` cells move from a generated documented absence to unlabeled, and the other 16
  take the next source's value.

**Reverse completion checkpoint (2026-11-26).** The next pass starts with the longest remaining
contracts to preserve the interrupted pass's starting portion. `DOC-29c516a4775b07d9` now has nine
near-gold fields from independent label/check passes and source-based machine review: six accepted
and three corrected. Seven previously unlabeled cells are filled; an unreviewed signature rule
and a CUAD-derived notice mapping are replaced by the reviewed bundle-specific readings. All
34,848 previously protected cells retain their values and presence. These are machine labels,
not human gold, and keep `use_as_truth: false`. The Hub revision and production overlay pin are
unchanged; this checkpoint is not a newly staged or published overlay.

**Corporate subclass checkpoint (2026-11-26).** Corporate records and correspondence are the
priority. The earlier 38 corporate absence annotations were withdrawn because those generic
fields do not apply to the source subclasses; their original submissions remain recoverable in
`data/labels/repair-artifacts/v93-20261126-scope-correction/`. Four correspondence absences remain
for hallucination checks and do not count as populated extraction coverage.

Dedicated runtime schemas now compose all eleven corporate subclasses from the pinned Dojo
registry. Independent source-only label/check passes add eight previously missing registered
entity fields on four subsidiary schedules: seven populated facts and one documented jurisdiction
absence. All seven populated additions are present in prepared truth and produce field-scoring
events. All 10,561 preceding catalog rows, 1,858 supplementary rows and 9,656 overlay field
payloads are preserved. The first subsidiary admission brought the overlay to 9,664 labels. Eight further pilot fields remain
held for identical-map independence checks or an ambiguous table token; raw submissions and
exact admission projections are committed under
`data/labels/repair-artifacts/v93-20261126-subclass-subsidiary001/`.

A further 15 populated entity facts on six board-resolution, power-of-attorney and charter-amendment
documents pass source, missing-only and scoring checks: 14 independent agreements and one
source-reviewed wording dispute. A multiple-grantor `principal` remains held because its
single-name schema does not represent both grantors cleanly. Their raw passes and exact
admission projections are in `data/labels/repair-artifacts/v93-20261126-subclass-diverse001/`.
A third admission adds 15 populated facts on seven incorporation, indenture and rights-instrument
documents (14 independent agreements and one source-reviewed exercise-price representation).
Those three admissions total 38 registered entity fields on 17 documents. The third batch
preserves original raw bytes in private checkpoints; its public exports normalize only source-path
metadata, preserving every field payload and labeler identity. Its archive is
`data/labels/repair-artifacts/v93-20261126-subclass-diverse002/`. The notebook evidence
checker now uses the corporate subclass and retains strict per-member/type/identity checks.

A fourth admission adds **33 fields on 17 subsidiary schedules: 32 populated scoring targets
and one documented jurisdiction absence**. Thirty-one independent agreements and two source
reviews support these additions. The reviews adopt the check pass's legal names, keeping
ownership and trade-name qualifications in evidence. Seven fields remain held for identical
maps or ambiguous source interpretation; neither evidence nor independence guards were changed.
Byte-identical raw passes, exact field projections and the preservation/scoring audit are in
`data/labels/repair-artifacts/v93-20261126-subclass-subsidiary002/`.

A fifth admission adds **12 fields on four charter/incorporation documents: seven populated
scoring targets and five documented absences**. Nine independent agreements and three explicit
full-source reviews support the additions. Fifteen fields on five other instruments remain
held because both source passes question their assigned subtype. Raw passes, exact projections,
review decisions and the preservation/scoring audit are in
`data/labels/repair-artifacts/v93-20261126-subclass-diverse003/`.

The five admissions total **83 registered entity fields on 38 documents: 76 populated scoring
targets and seven documented absences**. The overlay now has **9,739 labels**. Thirty-one
corporate fields remain held across these admissions.

At the corporate checkpoint, the missing-only inventory was 1,471 registered entity fields on 422 documents (see
`corporate_subclass_missing_coverage.json`). The flat CSV excludes those extension entities:
its three CSV outputs remain byte-identical, at 43,391 / 48,686 labeled cells (89.1%). These
counts describe static annotation coverage, not extraction performance. Machine near-gold labels
retain `use_as_truth: false`; these additions are not a release cut. Two correspondence
fields remain held for parser or independence-evidence handling. New production preparations
select the separately verified, landed rc.10 cut; frozen locks retain their earlier selection.
See [`rc10_selection_verification.json`](rc10_selection_verification.json).

**Merger critical-field checkpoint (2026-11-26).** Independent source-only label and check
passes, followed by a separate source review, add **16 previously missing populated fields
on three merger agreements**. The records cover parent/target roles, merger subsidiaries,
per-share cash or base stock exchange ratio, target termination fees and named financial/legal
advisors. Four reviews preserve the consideration exceptions, fee triggers and adjustment
conditions; the stock ratio adopts the check pass's explicit adjustment quote. All 16 additions
are present in prepared truth and produce field-scoring events. The separate MAUD headline is
unchanged. These are static eligibility checks, not extraction-performance measurements.

All 10,644 preceding catalog rows, 1,896 supplementary rows and 9,739 overlay field payloads
are preserved; the overlay now has **9,755 labels**. Twelve assigned fields remain unadmitted:
five depend on sections absent from a truncated source, two outside dates have conditional
extensions, two consideration fields conflict with the assigned mixed subclass, and three
absence answers have only a check pass. No absence or subclass correction is inferred.
Byte-identical raw submissions, exact admission projections, source ranges, four review
decisions and the preservation/scoring audit are in
[`merger-critical001`](../../../data/labels/repair-artifacts/v93-20261126-merger-critical001/README.md).

The flat consensus export changes only those 16 field cells: ten become labeled and six
replace earlier unreviewed readings. All 34,515 cells previously selected from Hub, owner,
reviewed interim, near-gold or subclass-review sources keep their values and presence. See
[`merger_critical001_csv_preservation.json`](merger_critical001_csv_preservation.json).
The [direct-field merger inventory](merger_direct_missing_coverage.json) still has 2,323 missing opportunities on 152 documents;
the pilot does not complete the class. Source-type holds, machine `use_as_truth: false`,
production rc.10 selection and frozen experiment locks remain in effect. This is not rc.11
or a newly staged release.

**Election and other merger subclasses (2026-11-26).** A second independent label/check
batch and scoped source adjudication add **13 populated fields on two agreements**. Three
reviews preserve share exclusions and election/proration/adjustment terms. All 13 produce
field-scoring events and preserve the preceding 10,660 catalog rows and 9,755 overlay field
payloads. Three assignments remain unadmitted: an unfinished exchange-ratio search and two
party/subsidiary fields whose preamble names conflict with the execution blocks. Exact passes,
projections, source ranges and audits are in
[`merger-critical002`](../../../data/labels/repair-artifacts/v93-20261126-merger-critical002/README.md).

The two merger batches total **29 populated fields on five agreements**, spanning all five
corpus merger subclasses, with **15 assignments unadmitted**. The overlay has
**9,768 labels**. That batch changed 13 admitted field cells (six populated, seven replacing
unreviewed readings) and kept 34,531 previously protected cells; see
[`merger_critical002_csv_preservation.json`](merger_critical002_csv_preservation.json).
Rebuilding those labels together with the 64 reviewed subclass corrections gives current
flat coverage of **43,408 / 48,686 (89.2%)**, while the direct merger inventory still
has **2,310 missing opportunities on 152 documents**. Subclass representation does not imply
complete field coverage. Neither batch changes the MAUD headline or constitutes rc.11.

The 2026-11-28 corporate subclass admission adds **457 near-gold labels on 131 dev-split
documents** (253 populated, 204 documented absences; 409 two-pass agreements and 48 reviewed
disputes), see
[`corporate-subclass-dev`](../../../data/labels/repair-artifacts/v93-20261128-corporate-subclass-dev/README.md).
The overlay has **10,225 labels**. With the subclass target cells above, 534 of the catalog's 540
corporate subclass labels reach this release (the other six belong to two documents whose reviewed
subclass is no longer `board_resolution`). No previously targeted cell changes value or presence.

The 2026-11-28 dev gate-gap admission adds **119 near-gold labels on 58 dev-split corporate
documents** (63 populated, 56 documented absences), see
[`corporate-gate-gaps-dev`](../../../data/labels/repair-artifacts/v93-20261128-corporate-gate-gaps-dev/README.md).
They fill every open gate-scored dev cell but one, a bracketed principal amount in a form indenture
that both passes held. 100 rest on two agreeing passes; a source-reading review settled the other
19, fifteen of them on documents whose check pass was a byte-identical copy and is withheld. The
overlay has **10,344 labels**. The rebuild changes exactly the 119 cells, all previously
unlabeled; no other cell changes value, presence, source or rule.

The 2026-11-28 calibration gate-gap admission adds **73 near-gold labels on 18 calibration-split
corporate documents** (36 populated, 37 documented absences), see
[`corporate-gate-gaps-calibration`](../../../data/labels/repair-artifacts/v93-20261128-corporate-gate-gaps-calibration/README.md).
They close every open gate-scored calibration cell in slices 100, 250 and 500. The cells left open
there are all on `heldout` documents, which the playbook does not label. 64 rest on two agreeing
passes; a source-reading review settled the other 9 (7 disputes, and 2 fields on a document whose
check pass was a byte-identical copy). These are in-sample labels, and the judge reference pool
now holds them. The overlay has **10,500 labels**. The rebuild changes exactly the 73 cells, all
previously unlabeled: 44,211 of 50,233 cells labeled (88.0%). No other cell changes value,
presence, source or rule.

Merger money admission now requires a source dollar marker attached to the same exact figure
in one quote. Foreign or ambiguous currencies remain held; symbols are never substituted.
The scoped guard covers both submission and stored-evidence checks and preserves legacy
contract/corporate matching. Non-adjacent or unrecognized currency qualifiers require source
review; the automated check does not certify every currency context.

**Source-type hold.** A bounded audit of the 61 records currently typed `officer_certificate`
found headings suggesting 53 designation/amendment instruments, seven incorporation/charter
instruments and one board resolution with an embedded designation. These are heuristic groups,
not corrected subtypes: only three sources were read fully. All 61 source hashes match the pin.
The four officer fields (244 opportunities) were held until corpus owners adjudicate
instrument type and compound-document boundaries. Since then, the corporate subclass rounds have
labelled them on 22 of these records against the reviewed subclass (19 in the dev round, 3 in the
calibration round). The instrument-type question is still open for the owners. An officer's filing attestation does not by
itself turn a designation into a standalone officer certificate. See the source excerpts,
inspection ranges and acceptance limits in
[`corporate_source_fit_officer_certificate.json`](corporate_source_fit_officer_certificate.json).

Five additional full-read source-type holds cover three bylaw instruments currently typed as
board resolutions, a correction instrument and a trust amendment. Their fifteen fields are
included in the held count above; no subtype is changed and no absence label is admitted.

Public source-path metadata is normalized to repository-relative paths in six files. The
original bytes remain in private checkpoints. Values, evidence, role attribution and all gold
overlay field payloads are unchanged; six supplementary records have path metadata changes.
See [`source_path_metadata_export_audit.json`](source_path_metadata_export_audit.json).

Twelve pre-existing populated core annotations conflict with their current subclass
applicability. They remain unchanged and are outside the missing-only admissions. The proposed
legacy notebook check was reverted after its existing overlay regression failed; no test was
excluded or relaxed. See
[`legacy_corporate_core_applicability_hold.json`](legacy_corporate_core_applicability_hold.json).

[`05_label_coverage_eda.ipynb`](../../../notebooks/05_label_coverage_eda.ipynb) inspects current
interim and near-gold snapshots at execution, with optional pinned cached-corpus comparisons,
subclass applicability, runtime field support and evidence drill-down. It reports populated
values and documented absences separately and makes no model-performance claim.

## Presence codes (provenance file)

| `presence` | Meaning |
| --- | --- |
| `populated` | A value was chosen. |
| `documented_absence` | The winning sources say the document has no such value (for example no adjuster named). The cell is blank, but the field **is** labeled. |
| `unlabeled` | No source labels this field for this document. Treat as missing, not as absent. |
| `disputed_unresolved` | Only a disputed value exists. Left blank for human review (1 cell, a contract field). |

In the main CSV, a blank cell is ambiguous on its own. Classify each blank from the provenance row
for that `(document_id, field)` (`presence` = `documented_absence` or `unlabeled`). The wide-row
counters `fields_labeled` and `label_completeness` are aggregates only; they cannot identify which
blank in a row is absence versus unlabeled.

## Other repairs

- **2,100 `"nan"` placeholder strings** on GNOTHEIA and BDR insurance rows are dropped. They sat in
  fields that do not apply to insurance claims (staged upstream for v9.4).
- **13 duplicate documents are flagged**, not removed: `duplicate_of` names the kept copy. When a
  reviewed subclass correction exists in a duplicate group, that reviewed document is kept.
  `exact_duplicate_count` and `normalized_duplicate_count` give the size of each group. Drop rows
  with a non-blank `duplicate_of` for de-duplicated analysis (upstream v9.4 removes 10).
- **66 subclasses corrected** by reviewed evidence (`subclass_changed`): 2 earlier reviews plus
  the 64 tier-A corrections of the 2026-11-27 strata audit. The v9.3 value is kept in
  `subclass_hub_v9_3`. Contract corrections also move the derived `cuad_family`, and the merger
  correction fills `merger_consideration` for DOC-4c27875ffea162d4.
- **Dates normalized** to `YYYY-MM-DD` (`YYYY-MM` when only month and year are given). Blank
  template dates such as `[___], 2020` count as absent. One malformed CUAD span stays as text.
- **Corporate `record_type`** keeps the Hub's coarser vocabulary (for example, charter amendments are
  `articles_of_incorporation`). The fine-grained type is in `subclass`.

## Limitations

- **Generated labels are not human-reviewed.** `generated_rule` labels are pattern matches, each
  with a verbatim quote, and spot checks found them right in most cases, but they are not
  gold. Filter on `chosen_source` in the provenance file if your analysis needs reviewed labels only.
- **Contracts:** 91 SEC EDGAR contracts have no CUAD annotation, so no CUAD ballot labels them.
  `effective_date`, `term_length` and `renewal_terms` stay unlabeled on all 91; `governing_law`
  is labeled on 28 of them by a `generated_rule` pattern match and unlabeled on the other 63 (it
  is labeled on 537 of all 600 contracts). A missing CUAD ballot is not a missing label: check
  `presence` before discarding a field. Their
  nine scored contract fields come from the near-gold overlay instead (agent label and check
  passes plus a reviewing model, not human gold). `expiration_date` is labeled on 315 contracts,
  `termination_notice_period` on 380 and `dispute_forum` on 282. `contract_value`,
  `payment_terms`, `territory` and `party_roles` have no CUAD category, so they are labeled only on
  the 268 contracts in the gold catalog.
- **Merger agreements:** several fields are found only where the agreement states them in a
  standard form (exchange ratio, termination fees, advisors, signatories). Signature pages are
  usually missing from the text. `merger_consideration` is never labeled for the `other` subclass.
- **Correspondence sender, recipient and date** come from the original email header where the
  corpus text lost it. The header is not in `doc_text`, so a model reading only the text cannot see it.
- The test split has only about 17 merger agreements. Per-class sample sizes are small for some
  subclasses (see the class table in the dataset card).
- Licenses follow the source corpora: CUAD and MAUD are CC BY 4.0 (The Atticus Project). For the
  other sources, see the dataset card.

## Rebuilding

```bash
.venv/bin/sandbox datasets pull        # caches v9.3 under data/cache/ (no LLM, no spend)
.venv/bin/python -I reports/datasets/mailroom-dataset-v9.3-label-repaired/build_label_repaired.py \
  --out reports/datasets/mailroom-dataset-v9.3-label-repaired/generated-YYYYMMDD
# optional: add --with-text for the gzipped text archive (not committed)
```

The builder refuses an existing `--out` directory and publishes by renaming a complete staged set,
so readers never see a mix of old and new release files. The build is deterministic and
network-free once the cache exists. `summary.json` pins the sha256 of every input byte it parsed
(including consumed Parquet shards) and of each output file. Rebuild timing is environment-dependent;
do not treat a prior “about five seconds” figure as a pinned measurement.
