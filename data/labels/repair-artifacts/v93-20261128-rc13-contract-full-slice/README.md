# rc.13 Phase 3: contract target fields in the full slice (2026-11-28)

This near-gold round feeds the `9.3.1-rc.13` staged cut. It labels the contract target fields
(`gl.TARGET_FIELDS`) that the rc.12 rounds left open in the full production slice, outside
slices 100, 250 and 500. Each document was read twice, independently, from its text alone: a label
pass and a check pass, run by different agents that never saw each other's output. A
source-reading review settled every dispute, and then audited the agreed cells that either pass
marked as low confidence. No `heldout` document was labelled.

## Queue

[`submissions/rc13-p3-queue.jsonl`](submissions/rc13-p3-queue.jsonl) holds 1,059 open cells on 171
documents (114 dev, 57 calibration), in 19 groups of up to 9 documents. The fields are
`agreement_date`, `contract_value`, `dispute_forum`, `expiration_date`, `party_roles`,
`payment_terms`, `signatories`, `termination_notice_period` and `territory`. Derived contract
fields (`document_name`, `term_length`, `renewal_terms`, `cuad_clauses`, `governing_law`) are not
labelled by hand. The pass brief and field briefs are the rc.12 Phase 1 ones, with paths changed.

## Admitted

1,018 near-gold labels on 166 documents (109 dev, 57 calibration): 621 populated and 397
documented absences. That is 96.1% of the queue.

- 990 labels on 138 new documents went through `add`. 28 labels on 29 documents the catalog
  already held went through `add --missing-fields`.
- 821 labels rest on two agreeing passes.
- **The review settled 197 labels:**
  - 150 accept the label;
  - 44 adopt the check pass;
  - 3 are corrections:
    - The `party_roles` of `DOC-e53347b00c241321`: Airsopure International Group, Inc. is the
      licensor.
    - The `payment_terms` and `termination_notice_period` of `DOC-67050576826b131b`, below.
- **Same-text twin.** `DOC-67050576826b131b` has the same text as the catalog's
  `DOC-f5a54932794ef16e`.
  - Its `payment_terms` and `termination_notice_period` now use the twin's catalog wording, so
    the stager does not hold both cells back for disagreeing.
  - The `payment_terms` correction supersedes the round's first-wave accept.
  - Both twins leave `contract_value` unlabeled, since the only amount is a euro rate.
- **Withheld checks.** Four check passes had fields identical to the label pass, so `add` does
  not count them as independent. They are withheld
  ([`submissions/rc13-p3-withheld-check.jsonl`](submissions/rc13-p3-withheld-check.jsonl)), and
  the reviewer read each clause:
  - three `party_roles` are accepted, each naming its value;
  - the `termination_notice_period` of `DOC-6dd99f331bcd903b` is rejected and left out of the
    admission.

## Left unlabeled (41 cells)

### Rejected by review (28 cells)

Neither reading is clean truth, so the cell stays open rather than being guessed. 26 are
`review_rejected` rows in the supplementary store. Two were left out of the admission before
`add`, because a reject is not a second reading of a single-pass cell:

- `DOC-6dd99f331bcd903b` `termination_notice_period` (withheld check);
- `DOC-a41ac47e80ec56c9` `contract_value`: RMB only, and the check pass gave nothing.

The 13 rejects from the dispute review:

- **Redacted:**
  - two notice periods or cure periods;
  - one compensation schedule;
  - one arbitration seat.
- **Not the agreement's notice:** a cure period that ends one trademark licence, not the
  agreement.
- **Not the contract's consideration:**
  - a renewal fee in an unsigned template;
  - a prepayment credit and a non-binding target. This was a Fable tie-break.
- **Currency:** an RMB-only amount.
- **Secondary scope:** three "worldwide" readings that qualify a secondary licence, not the main
  grant.
- **Ambiguous:**
  - a licence that ends by destroying copies;
  - a fee whose payer and timing are unclear.

### Rejected by the low-confidence audit (15 cells)

63 agreed cells had a pass confidence below 0.6. The reviewer re-read them against the field
definitions and catalog precedent: recurring fees, "up to" amounts and stated purchase prices are
already near-gold `contract_value` labels, so those cells were kept. These were rejected:

- **`contract_value`:**
  - one instalment of a fixed-price schedule;
  - the top tier of a tiered monthly fee;
  - a per-quarter reimbursement cap;
  - offering proceeds paid by investors.
- **`contract_value`, Fable tie-breaks:**
  - a contingent milestone beside a Net Sales-based fee;
  - a capped side-financing facility;
  - a joint venture's registered capital;
  - a ceiling on capital contributions.
- **`expiration_date`, Fable tie-break:** a per-store sale end date in an agreement with no
  term clause.
- **`territory`:**
  - an area from which a party may not be excluded;
  - the focus of a cooperation, which is not a grant territory.
- **`signatories`:** three names printed under blank signature lines, or with no signature
  line, in unsigned copies.
- **`termination_notice_period`:** the withheld-check cell above.

### Left out by the passes (13 cells)

No pass gave a value that could be admitted:

- **Nine `contract_value` cells:**
  - **another currency:** EUR on three documents (the twins and one licence), RMB on two, GBP,
    NTD and kina on one each;
  - **unparseable:** "USD$6.745.000", which uses period thousands separators.
- **Two `agreement_date` cells:** the date is printed in a form the gate cannot quote
  verbatim (a rule line splits "31 December, 1996"; "3-14-18").
- **Two `expiration_date` cells:**
  - "March 18. 2021" cannot be quoted as a date;
  - on `DOC-3ce2fb9a704b18e6`, only the check pass gave a reading: a documented absence, since
    the initial term runs to a day before an anniversary. One reading is not near-gold, so the
    cell stays open.

## After the round

- **Contract coverage** in the label-repaired release goes from 7,123 to 8,141 of 10,200 cells
  (69.83% to 79.81%). Populated cells go from 5,433 to 6,054, and documented absences from 1,690
  to 2,087.
- **Full slice:** no contract target cell is open on a dev or calibration document except the 41
  above.
  - The remaining open contract cells are derived and CUAD-style fields on CUAD-empty documents:
    505 dev cells on 147 documents and 102 calibration cells on 45.
  - Every other open scored cell is on a `heldout` document.
- **Overlay:** 12,142 labels (11,124 before).
- **Release rebuild:**
  - It fills exactly the 1,018 previously unlabeled cells. Repaired cells go from 44,835 to
    45,853, and unlabeled cells from 5,397 to 4,379.
  - No existing value changes. Only the per-document `fields_labeled` and `label_completeness`
    move.
  - `values_moved_by_reviewed_precedence` is unchanged.
- **In-sample:** calibration labels are in-sample. The judge reference pool now holds them: it
  grows from 44 to 94 contract documents. Report a score on calibration documents as in-sample.
- **Subclass registry:** label counts change, plus three field verdicts (contract `ip`
  `expiration_date` and `party_roles`, contract `service` `territory`) that move from `thin` to
  `constant`.

## Files

`INDEX.json` lists every file with its sha256 and whether `gold_labels.py add` read it.

- **Passes:** the `g01`–`g19` `raw-label` and `raw-check` files are the passes as written.
- **Disputes:** `gold_labels.py disputes` output, in three review waves (`w1`, `w2a`, `w2b`).
- **Reviews:** the `raw-review` files are the review lines.
  - **Wave 1 and wave 2** (`w1`, `w2a`, `w2b`) settle the disputes.
  - **`w3-lowconf`** holds the low-confidence audit.
  - **`w3-twin`** holds the twin corrections.
  - **`w3-withheld`** holds the withheld-check decisions.
- **What `add` read:** the `mf-*` and `new-*` files are what the two `add` calls read. The raw
  passes and reviews are split by whether the catalog held the document. Withheld checks, empty
  submissions and cells settled only by a reject are left out.
- **Inputs:** the `queue`, `pass-brief` and `field-briefs` files are the round's inputs.

The commands were (corpus pinned at Hub revision `ff4ca546d4346991628c2616ae014afc15e9fe04`):

```bash
scripts/gold_labels.py add --corpus <dir> --revision ff4ca546… --label rc13-p3-mf-label.jsonl --check rc13-p3-mf-check.jsonl --review rc13-p3-mf-review.jsonl --missing-fields
scripts/gold_labels.py add --corpus <dir> --revision ff4ca546… --label rc13-p3-new-label.jsonl --check rc13-p3-new-check.jsonl --review rc13-p3-new-review.jsonl
scripts/gold_labels.py check
scripts/gold_labels.py overlay
```

These are machine near-gold labels, not human gold. Reviews name their reviewer
(`claude-opus`, role `review`). A Fable tie-break says so in its note.
