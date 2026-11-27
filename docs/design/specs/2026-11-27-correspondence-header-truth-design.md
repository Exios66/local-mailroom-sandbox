# Correspondence header truth the model cannot see

**Status.** Proposal, 2026-11-27. Needs an owner decision: it changes how a recorded decision is
applied on the headline ("those labels stay as truth", [staged label overlay](../../staged-label-overlay.md)).
Nothing here is implemented.

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

- **Scope.** Correspondence only; the four header fields only; only where the field's truth comes
  from an `original_header` label. The check is per document: a field whose quoted header line does
  appear in `doc_text` stays scored, so a restored corpus turns the fix off document by document.
- **Mechanics.** Like SHF-015: the field is dropped from both sides on the hotfixed pass, its presence
  becomes `pending_annotation`, and the row lists it under `header_unseen`. The gate does not count a
  dropped field toward `min_labelled`, and the lowest-field diagnosis (`gate_causes._field_scores`)
  skips it.
- **Identity.** It takes the next free `SHF-*` ID when it lands (`SHF-019` if #450 lands first with
  SHF-017 and SHF-018). It fingerprints the scoring seam and `interim_reviews.jsonl`. Its lock entry
  changes the run identity, so preflight refuses to resume a run locked before it.
- **Retirement.** Retire it when the pinned corpus revision restores the headers. The per-document
  text check makes it a no-op on such a revision, and a test asserts that.
- **Reporting.** Every report keeps the raw score. A campaign comparing runs across the change
  compares raw to raw.

## How we will measure it before landing

No committed report has per-field correspondence scores. Before landing A:

1. Rescore stored correspondence answers offline, with no new model call, with and without A. The
   owner names the runs (for example the slice-0100 production run).
2. Report per field: the share of misses that are header-only, and the headline before and after.
3. Land A only if the dropped cells account for the misses this design predicts. A field that the
   model gets right from a quoted reply despite the stripped header stays scored, because its header
   line appears in the text.

## Decision needed

- Approve A as an interim scoring hotfix, or keep D until B ships.
- If approved, confirm which runs to rescore for the before/after evidence.
