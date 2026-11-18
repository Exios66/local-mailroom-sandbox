# Interim ground-truth labels

These are the unpublished enhancements to the mailroom-dataset `ground_truth` labels. They act as ground truth until the next dataset revision publishes them.

**Do not edit these files by hand.** `scripts/interim_labels.py` builds them, and `scripts/interim_labels.py check` and `tests/test_interim_labels.py` verify them against `MANIFEST.json`.

## Contents

| File | Contents |
| --- | --- |
| `<class>.jsonl` | One record per document: `doc_id`, `doc_subclass`, `doc_sha256` (the exact text the labels were read from), `labels`, and `source` (the extraction run and prompt, the gate run, the question set, the verdict). |
| `MANIFEST.json` | Sources, admission rules, counts, the admission precision proxy, the file hashes, and the dojo issue that supersedes each class. |

Each label has a `status`:

| Status | Truth | Meaning |
| --- | --- | --- |
| `gap_fill` | yes | The Hub has no label. A real extraction the gate supports (field support >= 0.9) and whose every token is in the document. |
| `derived` | yes | Computed from the row, with no model involved: `cms_source_table`, `record_type` and `communication_type` from `expected_subclass`. |
| `correction` | yes | The Hub label is a known defect. The value is checked against the Hub's own CUAD evidence (`cuad_party_spans`, `cuad_agreement_date`), or comes from a reviewed read of the message (see below). |
| `disputed` | **no** | The Hub label and a gate-supported extraction disagree. It carries `hub_value` (and `hub_source`) for human review. |

## Reviewed labels

`data/labels/review/interim_reviews.jsonl` holds labels a reviewer settled, one line per label. `scripts/interim_labels.py review` writes them into the overlay. Each one replaces the label of its field, or adds it, together with a record for a document that has none. A reviewed label carries `review` (`reviewer`, `note`, `file`), `evidence`, and `replaced`, the label it replaced.

| `basis` | Status | Fields | Rule |
| --- | --- | --- | --- |
| `review_read_message` | `correction` | correspondence `intent` | The review read the message and found the Hub value wrong. The label keeps `hub_value`. The value must be in the intent vocabulary. |
| `original_header` | `gap_fill` | correspondence `sender`, `recipient`, `additional_recipients`, `communication_date` | The corpus text lost the email header. The value comes from the original message in the CMU Enron maildir. `evidence` quotes the header lines (`X-From`/`From`, `X-To`/`To`, `X-cc`/`Cc`, `Date`) with the maildir file. Every name token must be in the quoted lines, and a date must equal the `Date` header. |

The manifest lists each review file with its sha256 (`reviews`). `check` fails when a listed file changed and was not applied again, or when one of its labels is missing or differs in the overlay. `build` applies the listed files again after a rebuild, so a new gate run never drops a reviewed label.

The header values are not in the corpus text, so an extraction from that text cannot find them. Until the dataset restores the headers, a model is scored against values it cannot see.

## Use

Nothing reads these files by default. A run opts in with:

```yaml
dataset:
  interim_labels: true
```

The run then merges the truth labels into its locked rows' `expected_fields`; Hub labels always win, except that a `correction` replaces the Hub value it names. It records the overlay's sha256 in both the spec hash and the lock (`dataset.metadata.interim_labels`).

`apply_overlay` also takes a Hub `ground_truth` parquet row as it is. It matches the row on `document_id`, and on `content_sha256` when the row has no `doc_text`, then writes the labels back into `gt_fields`. `interim_labels.apply_overlay_parquet` (or `scripts/interim_labels.py apply`) does the same for a whole shard. The output keeps the shard's columns and types and adds an `interim_labels` column, which holds JSON `{"fields", "overlay_sha256"}` on rows that took labels and null on the rest. `check --prune` never drops a reviewed label: it reports one the Hub supersedes, and keeps it.

## Updates

```bash
python scripts/interim_labels.py build --add-run <new gate run>   # after every gate run
python scripts/interim_labels.py build                            # rebuild from the listed runs
python scripts/interim_labels.py check                            # integrity + staleness
python scripts/interim_labels.py review                           # apply the listed review files again
python scripts/interim_labels.py review --apply <file.jsonl>      # apply a new review file
python scripts/interim_labels.py check --rows <hub rows.jsonl | ground_truth.parquet> --prune   # after a Hub revision
python scripts/interim_labels.py apply --parquet <ground_truth.parquet> --out <overlaid.parquet>
```

Rules and evidence: `docs/EXTRACTION_GATE_VETTING.md`.
