# Correspondence header truth the model cannot see

**Status.** Approved by the owner on 2026-11-27 (option A) and implemented as scoring hotfix
SHF-019 ([scoring hotfixes](../../scoring-hotfixes.md)). It changes how a recorded decision is applied
on the headline ("those labels stay as truth", [staged label overlay](../../staged-label-overlay.md)):
the labels stay as truth, and the raw score keeps scoring them.

**Goal.** Stop scoring correspondence extractions on header values the document text does not
contain, until the dataset restores those headers. Keep the full truth visible next to the headline.

## Problem

The cleaned corpus text dropped the Enron email header from many messages. The interim overlay then
restored the header values as truth from the original CMU maildir (`basis: original_header`,
[interim README](../../../data/labels/interim/README.md)). The truth is correct about the message,
but the model reads only `doc_text`, so it cannot produce those values. Every such field is a
predictable miss that says nothing about the model.

| Field | Header-only truth cells | dev | calibration | heldout | pool |
| --- | ---: | ---: | ---: | ---: | ---: |
| `communication_date` | 654 | 132 | 229 | 163 | 130 |
| `recipient` | 455 | 90 | 171 | 104 | 90 |
| `additional_recipients` | 350 | 69 | 118 | 90 | 73 |
| `sender` | 336 | 70 | 119 | 67 | 80 |
| **Total** | **1,795** on 735 documents | | | | |

Source: `queues/header_restoration.csv` of staged cut rc.10 (735 documents). The 1,795 cells are
exactly the `original_header` lines in `data/labels/review/interim_reviews.jsonl`. Correspondence
has about 4,000 entity-field truth cells, so about 45% of them are header-only. Splits are from
`config/splits/runbook-v2/assignments.jsonl`.

These four are the correspondence entity fields, and correspondence is a gated class in the
production slice gate. On slice 0100 the correspondence headline is 0.544 after SHF-015
([scoring hotfixes](../../scoring-hotfixes.md)), against 0.897 for corporate records.

This also conflicts with the labeling rule "Only label from the text"
([labeling guide](../../gold-labels/LABELING_GUIDE.md), ground rule 2). A near-gold pass on the same
text would label these fields from the top message instead: the signature as the sender, the
salutation as the recipient, and no date.

## Options

| Option | What it does | Cost | Verdict |
| --- | --- | --- | --- |
| **A. Scoring hotfix (proposed)** | On the hotfixed headline, a correspondence field whose only truth is an `original_header` label, and whose quoted header lines are not in `doc_text`, is left out of truth and prediction and named under `header_unseen`. The raw score (`raw_dojo`) keeps it. | Small sandbox change, dual-reported, retires itself (below). | Recommended until B ships |
| B. Restore the headers in the corpus | The next dataset release writes the header lines back into `doc_text` (already planned in the rc.10 manifest). | Upstream release; nothing to do here. | The real fix; A retires on it |
| C. Relabel from the visible text | Replace the header values with what the top message shows. | Throws away correct truth that B makes scoreable again. | Rejected |
| D. Do nothing | Keep scoring the 1,795 unseeable cells. | Correspondence entity scores stay depressed by a dataset defect. | Rejected |

## Option A in detail

- **Scope.** Correspondence only; the four header fields only; only where the field's truth is
  still the `original_header` label's value (a near-gold or staged label that replaced it is scored).
  The check is per document and deliberately generous: a field stays scored when the text contains
  any of its quoted header lines, the value after a header line's colon (a quoted reply's
  `From: jeff.dasovich@enron.com`), or any item of the label value (a signature, a name in the body),
  with case, whitespace, periods and commas folded. A restored corpus turns the fix off document by document.
- **Mechanics.** Like SHF-015: the field is dropped from both sides on the hotfixed pass, its presence
  becomes `pending_annotation`, and the row lists it under `header_unseen`. The gate does not count a
  dropped field toward `min_labelled`, and the lowest-field diagnosis (`gate_causes._field_scores`)
  skips it.
- **Identity.** `SHF-019` (`SHF-017` and `SHF-018` are reserved for #450). It fingerprints the
  scoring seam (`score_extraction_row`), the gate (`labelled_count`, `_fix_accuracy`), the diagnosis
  (`_field_scores`) and `interim_reviews.jsonl`. Its lock entry changes the run identity, so
  preflight refuses to resume a run locked before it.
- **Retirement.** Retire it when the pinned corpus revision restores the headers. The per-document
  text check makes it a no-op on such a revision, and a test asserts that.
- **Reporting.** Every report keeps the raw score. A campaign comparing runs across the change
  compares raw to raw.

## Measurement

Measured offline on the cached Hub v9.3 corpus (revision `ff4ca546`), with no model call:

| Truth preparation | Cells dropped | `sender` | `recipient` | `additional_recipients` | `communication_date` | Documents | Below `min_labelled` 2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Staged overlay `9.3.1-rc.9` (production slices) | 1,470 | 244 | 348 | 226 | 652 | 709 of 1,000 | 0 |
| Interim and near-gold overlays | 1,477 | 244 | 348 | 233 | 652 | 709 of 1,000 | 6 (2 dev, 1 calibration, 3 held-out) |

Of the 1,795 header cells, the rest stay scored because the text shows them (mostly a name in a
quoted reply or a signature) or another label replaced the header value. A perfect answer scores
1.0 on every affected document, and writing each document's quoted header lines back into its text
drops nothing (the retirement check, also a test).

### Still to do: the stored-answer rescore

No committed report has per-field correspondence scores, and no stored run answers are in this
checkout, so the answer-side check is still open:

1. Rescore stored correspondence answers offline, with no new model call, with and without A. The
   owner names the runs (for example the slice-0100 production run).
2. Report per field: the share of misses that are header-only, and the headline before and after.
3. Merge SHF-019 only if the dropped cells account for the misses this design predicts. A field that
   the model gets right from a quoted reply despite the stripped header stays scored, because the
   text shows it.

## Decisions

- 2026-11-27: the owner approved A as an interim scoring hotfix until B ships.
- Open: which stored runs to rescore for the answer-side evidence.
