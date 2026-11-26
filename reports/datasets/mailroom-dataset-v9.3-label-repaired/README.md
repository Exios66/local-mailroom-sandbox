# Mailroom Dataset v9.3: label-repaired CSV release

A partially labeled CSV release of
[`Lucius-Morningstar/mailroom-dataset`](https://huggingface.co/datasets/Lucius-Morningstar/mailroom-dataset)
**v9.3** (Hub revision `ff4ca546d4346991628c2616ae014afc15e9fe04`). It covers 3,302 business and
legal documents in five classes. Coverage is **89.1%** of per-class target fields (43,391 labeled,
5,217 unlabeled, 78 disputed/unresolved)—not a complete labeling. It is one snapshot of a dataset
that is still being developed, not the final release.

The published v9.3 ground truth labels 24,812 of the 48,686 per-class target fields (51.0%). This
release labels **43,391 (89.1%)**. Each added or changed label was chosen by a consensus vote over
every label source in this repository, and the vote that chose it is kept in the provenance file.

These flat per-class counters are not scored-field coverage. They omit corporate subclass
extension entities and include documented absences. The 2026-11-26 scope correction withdraws
38 recent corporate annotations outside their subclass's applicable fields; four correspondence
absences remain for hallucination checks and are not new populated extraction targets. Raw
submissions and the preservation audit remain in
[`repair-artifacts`](../../../data/labels/repair-artifacts/v93-20261126-scope-correction/README.md).
New corporate collection must follow the registered subclass schema and source evidence.

## Files

| File | Rows | Contents |
| --- | ---: | --- |
| `mailroom_dataset_v9.3_label_repaired.csv` | 3,302 | One row per document: identifiers, metadata, text statistics, a 280-character text preview, every label field, and per-row completeness counters. **The main analysis file.** |
| `mailroom_dataset_v9.3_label_repaired_label_provenance.csv` | 48,688 | One row per document and target field (plus the 2 subclass changes): the chosen value, its presence code, the winning source, every source's vote, the agreement and the evidence quote. |
| `mailroom_dataset_v9.3_label_repaired_field_completeness.csv` | 74 | Per class and field: how many documents are labeled in v9.3 and here, populated or documented absent, still unlabeled, disputed, and conflicts resolved. |
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
| `corporate_record` | 450 | 9 | 54.6% | 91.1% |
| `merger_agreement` | 152 | 18 | 0.0% | 43.9% |

The target fields of each class are the fields of the class's extraction schema in the vendored
`llm-dojo-scoring`, leaving out the fields the schema marks `not_applicable`. Insurance
`claim_checklist` is left out as well: it is not used in the experiments or in production, and no
source labels it. Corporate `filing_number` is kept as an extra field. A field that belongs to another class is left blank.

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
most total weight wins, and a tie goes to the better-reviewed source. A short `cuad_span` phrase
that a longer label contains (the same numbers and most of the same words) counts as a vote for
that label, and the label keeps its fuller wording. `agreement` records
`unanimous`, `single_source` or `k-of-n`, and `weight_share` records the winner's share of the
weight. A vote with three or more competing values whose winner holds under half of the weight is
flagged `needs_human`; none occurred.

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

The four admissions total **71 registered entity fields on 34 documents: 69 populated scoring
targets and two documented absences**. The overlay now has **9,727 labels**. Sixteen corporate
fields remain held across these admissions.

The missing-only corporate inventory is 1,483 registered entity fields on 426 documents (see
`corporate_subclass_missing_coverage.json`). The flat CSV excludes those extension entities:
its three CSV outputs remain byte-identical, at 43,391 / 48,686 labeled cells (89.1%). These
counts describe static annotation coverage, not extraction performance. Machine near-gold labels
retain `use_as_truth: false`; these additions are not a release cut. Two correspondence
fields remain held for parser or independence-evidence handling. New production preparations
select the separately verified, landed rc.10 cut; frozen locks retain their earlier selection.
See [`rc10_selection_verification.json`](rc10_selection_verification.json).

**Source-type hold.** A bounded audit of the 61 records currently typed `officer_certificate`
found headings suggesting 53 designation/amendment instruments, seven incorporation/charter
instruments and one board resolution with an embedded designation. These are heuristic groups,
not corrected subtypes: only three sources were read fully. All 61 source hashes match the pin.
The four officer fields (244 opportunities) remain unassigned until corpus owners adjudicate
instrument type and compound-document boundaries. An officer's filing attestation does not by
itself turn a designation into a standalone officer certificate. See the source excerpts,
inspection ranges and acceptance limits in
[`corporate_source_fit_officer_certificate.json`](corporate_source_fit_officer_certificate.json).

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
| `disputed_unresolved` | Only a disputed value exists. Left blank for human review (78 cells, all contract fields). |

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
- **2 subclasses corrected** by reviewed evidence (`subclass_changed`). The v9.3 value is kept in
  `subclass_hub_v9_3`.
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
