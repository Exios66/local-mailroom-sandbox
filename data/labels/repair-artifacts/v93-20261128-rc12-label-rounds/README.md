# rc.12 label rounds: contract slice gaps and corporate calibration gaps (2026-11-28)

These two near-gold rounds feed the `9.3.1-rc.12` staged cut. Each document was read twice,
independently, from its text alone: a label pass and a check pass, run by different agents that
never saw each other's output. A source-reading review settled every dispute. No `heldout`
document was labelled.

## Phase 1: contract target fields in the production slices

- **Queue** ([`submissions/rc12-p1-queue.jsonl`](submissions/rc12-p1-queue.jsonl)): 257 open
  cells on 38 dev and calibration documents. The cells are contract target fields
  (`gl.TARGET_FIELDS`) that slices 100, 250 and 500 score, plus two correspondence cells and one
  corporate cell. Derived contract fields (`document_name`, `term_length`, `renewal_terms`,
  `cuad_clauses`, `governing_law`) are not labelled by hand.
- **Admitted:** 246 near-gold labels on 36 documents (21 dev, 15 calibration). 157 are populated
  and 89 are documented absences. 245 are contract labels, and one is the correspondence
  `sender` of `DOC-f7af031d61f7d7f5`.
  - 196 rest on two agreeing passes.
  - The review ([`submissions/rc12-p1-new-review.jsonl`](submissions/rc12-p1-new-review.jsonl))
    settled 50 disputes: 45 accept the label and 5 adopt the check pass.
- **Rejected:** 8 disputes are left unlabeled because neither reading is clean truth:
  - redacted royalty terms;
  - two non-dollar amounts (RMB, EUR), which the brief leaves unlabeled rather than absent;
  - an OCR-garbled end date;
  - a renewal fee that is not the contract's consideration;
  - a pipeline route offered as a territory;
  - a pre-commencement cut-off offered as a notice period;
  - a party-role reading the text does not state with a role word.
- **Left out by both passes:**
  - the `communication_date` of `DOC-ca359bac49205614`: the day-first stamp `02/11/2000` cannot be
    quoted as 2000-11-02;
  - the `principal_amount` of `DOC-51092450a52e256c`: a draft whose every amount is bracketed.

## Phase 2: corporate gate-scored fields on calibration documents

- **Queue** ([`submissions/rc12-p2-queue.jsonl`](submissions/rc12-p2-queue.jsonl)): 385 open
  gate cells on 100 calibration-split corporate documents. The dev and calibration rounds before
  this one closed slices 100–500; these cells are in the full slice.
- **Admitted:** 378 near-gold labels on 100 documents (195 populated, 183 documented absences):
  345 through `add --missing-fields` on the 93 documents the catalog held, and 33 through `add` on
  7 new documents.
  - 351 rest on two agreeing passes.
  - The review ([`submissions/rc12-p2-mf-review.jsonl`](submissions/rc12-p2-mf-review.jsonl),
    [`submissions/rc12-p2-new-review.jsonl`](submissions/rc12-p2-new-review.jsonl)) settled 27:
    - 25 accept the label;
    - 2 adopt the check pass: `securities_series` without the rate blanks, and one
      `amended_provisions` item per provision, as the guide asks;
    - 2 of the 25 accepts are on `DOC-8d57a41d7e3dd5d7`. Its check pass was a byte-identical copy
      of the label and is withheld
      ([`submissions/rc12-p2-withheld-check.jsonl`](submissions/rc12-p2-withheld-check.jsonl));
      the reviewer read the whole 1,138-character exhibit.
- **Rejected:** 5 disputes are left unlabeled:
  - an authorized capital whose every count is a `[·]` blank;
  - two multi-class asset-backed principal amounts with no stated aggregate (summing is not
    allowed);
  - one maturity spread over four class dates;
  - a warrant indenture's "Warrants", which names the instrument, not a series.
- **In-sample:** calibration labels are in-sample. The judge reference pool now holds them: it
  grows from 33 to 44 contract and from 120 to 122 corporate documents. Report a score on
  calibration documents as in-sample.

## After the rounds

- **Slices 100, 250 and 500:** the only open, labelable, non-held-out cells are the 9 contract
  cells rejected above (slice 500: 5 dev, 4 calibration).
- **Full slice:**
  - 1,059 contract target cells are still open (696 dev, 363 calibration), outside the production
    sub-slices;
  - 7 corporate calibration cells (the rejects and left-outs);
  - 1 corporate dev cell;
  - 1 correspondence calibration cell.
  - Every other open scored cell is on a `heldout` document.
- **Overlay:** 11,124 labels (10,500 before).
- **Release rebuild:**
  - It fills exactly the 624 previously unlabeled cells. Repaired cells go from 44,211 to 44,835
    of 50,233, and unlabeled cells from 6,021 to 5,397.
  - `values_moved_by_reviewed_precedence` is empty, and `label_cells_disputed_unresolved` is
    unchanged.

## Corrections from PR review

After admission, PR #474 review found two labels worth correcting from the source
([`submissions/rc12-pr474-review-corrections.jsonl`](submissions/rc12-pr474-review-corrections.jsonl),
applied with `gold_labels.py review`):

- `DOC-9baab4e28bbe8197` `payment_terms`: the accepted wording dropped the second trigger. It now
  reads "within fifteen (15) Days of the invoice date or resolution of any dispute, if applicable".
- `DOC-064eb91826ef5b98` `instrument_kind`: `unit purchase option`, as the title names it. Both
  passes had chosen `warrant`, the nearest listed kind.

The admitted totals stay 624; these two are now `near_gold_reviewed`.

## Files

`INDEX.json` lists every file with its sha256 and whether `gold_labels.py add` read it.

- The `raw-*` files are the passes as written.
- The `mf-*` and `new-*` files are what the four `add` calls read: the raw passes split by whether
  the catalog held the document. They exclude the two Phase-1 documents with nothing to add and
  the withheld check.
- The `queue`, `pass-brief` and `field-briefs` files are the rounds' inputs.
- The `disputes` files are `gold_labels.py disputes` output.

The commands were (corpus pinned at Hub revision `ff4ca546d4346991628c2616ae014afc15e9fe04`):

```bash
scripts/gold_labels.py add --corpus <dir> --revision ff4ca546… --label rc12-p1-mf-label.jsonl --check rc12-p1-mf-check.jsonl --missing-fields
scripts/gold_labels.py add --corpus <dir> --revision ff4ca546… --label rc12-p1-new-label.jsonl --check rc12-p1-new-check.jsonl --review rc12-p1-new-review.jsonl
scripts/gold_labels.py add --corpus <dir> --revision ff4ca546… --label rc12-p2-mf-label.jsonl --check rc12-p2-mf-check.jsonl --review rc12-p2-mf-review.jsonl --missing-fields
scripts/gold_labels.py add --corpus <dir> --revision ff4ca546… --label rc12-p2-new-label.jsonl --check rc12-p2-new-check.jsonl --review rc12-p2-new-review.jsonl
```

These are machine near-gold labels (`use_as_truth: false` in the catalog), not human gold.
