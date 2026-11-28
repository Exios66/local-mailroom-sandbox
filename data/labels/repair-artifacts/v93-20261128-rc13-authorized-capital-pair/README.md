# rc.13 repair: one authorized_capital wording for a same-text pair (2026-11-28)

`DOC-18f682a3054d35c5` and `DOC-3c328f7374a079a9` have the same text (`content_sha256`
`e888213d…`): Nevada articles of incorporation filed 1999-09-08, bundled with later amendments.
Both near-gold `authorized_capital` labels quote the same article:

> FOURTH: The total authorized capital stock of the corporation is 20,000,000 at 0.0001 par value.

They differed only in wording:

- `DOC-18f682a3054d35c5` kept the article's lead-in: "The total authorized capital stock of the
  corporation is 20,000,000 at 0.0001 par value."
- `DOC-3c328f7374a079a9` gives the terms alone: "20,000,000 at 0.0001 par value".

The `9.3.1-rc.12` stager holds back the conflicting values of documents that share a text, so both
cells were unlabeled in that cut (`queues/needs_human.csv`, reason "documents with the same text
disagree on this field").

**Decision.** The terms-only wording. It is the catalog's majority form (29 of 44 populated
`authorized_capital` labels), and the check pass on `DOC-18f682a3054d35c5` gave it too. The
evidence is unchanged.

**Not changed.** Both labels keep the original article's capital, not the 100,000,000 shares at
$0.00001 that a later bundled amendment sets. Each label's `effective_date` (1999-09-08) and its
reviewed subclass (`articles_of_incorporation`, SHF-013) come from that first instrument, and both
passes on both documents chose it.

`review.jsonl` was applied with
`scripts/gold_labels.py review --corpus <pinned corpus dir> --review review.jsonl`. The label is
machine near-gold (`use_as_truth: false`), now `near_gold_reviewed`, not human gold.
