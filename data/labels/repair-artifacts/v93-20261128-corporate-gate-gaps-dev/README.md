# Corporate gate-scored gaps, dev split

After the corporate subclass round, 120 dev-split corporate cells that the production gate counts
were still unlabeled, on 59 documents (`label_eda.py rows --split dev --tier gate --presence
unlabeled,disputed_unresolved`). Most were `filing_number` (34) and charter amendment fields. This
round labels exactly those cells from the text alone, with two independent passes per document,
and holds no document out for its subclass: `gold_labels.py` now checks fields against the
reviewed subclass (SHF-013).

- **Admitted:** 119 near-gold labels on 58 documents (63 populated, 56 documented absences), all
  through `gold_labels.py add --missing-fields`.
- **Settled by:**
  - 100 labels rest on two agreeing passes;
  - a source-reading review (`submissions/corp-gate-dev-review.jsonl` and
    `submissions/corp-gate-dev-gE-review.jsonl`) accepted the other 19:
    - 4 were disputes: an `authorized_capital` worded two ways, a summed principal amount, and two
      amounts the check left out of specimen forms;
    - 15 are on 11 documents whose check pass was a byte-identical copy of the label. Most are
      single-fact records, such as one filing-number stamp.
- **Withheld checks** (`submissions/corp-gate-dev-withheld-check.jsonl` and
  `submissions/corp-gate-dev-gE-withheld-check.jsonl`):
  - the 11 identical copies, which the independence guard rightly refuses as a second reading;
  - 3 check passes with no fields;
  - the check on `DOC-51092450a52e256c`, whose label pass had no fields.

  `add` takes a document without a check pass only when a review settles every field it labels.
  The reviewer read the source for each one; the notes in the review files say what was read.
- **Follow-up pass (`gE`):** the first four batches left 3 cells out. Two are now labeled:
  - `exercise_price` on `DOC-732b812b7d9d9653` is "$0.001". The warrant states "$.001 per Share",
    which the money gate refused until it learned that a dollar figure may drop its leading zero.
    The check was an identical copy, so a review settles it.
  - `instrument_kind` on `DOC-7ffe745a67032ac5` is a documented absence. A common-stock
    subscription agreement fits none of the schema's five kinds, and both passes agree.
- **Still open (1 cell):** `principal_amount` on `DOC-51092450a52e256c`. Every amount in this form
  indenture is a bracketed placeholder (`$[35,000,000]`), and both passes held it.
- **Earlier hold-outs closed:** the four documents the subclass round held out for identical
  passes are now admitted, two by agreement and two by review.

`INDEX.json` lists every file with its sha256 and whether it was an admission input. The `raw-*`
files are the passes as written. The `g?-label` and `g?-check` files are what `add` read: the raw
passes minus the documents whose label had no fields, and minus the withheld checks. The
`queue` and `pass-brief` files are the round's inputs.

These are machine near-gold labels (`use_as_truth: false` in the catalog, not human gold). The
label-repaired release rebuild fills exactly these 119 previously unlabeled cells, and no other
cell changes value, presence, source or rule.
