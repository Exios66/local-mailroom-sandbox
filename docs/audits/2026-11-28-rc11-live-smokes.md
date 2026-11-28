# rc.11 OpenRouter live smokes: failure points (2026-11-28)

Three live pipeline smokes on the rc.11 staged labels, all agents on `qwen/qwen3.7-flash` and the
Luna Decisions model on the sorter reviewer only. Specs: `config/runs/live-smoke-rc11-0025.yaml`,
`-0025-fix1.yaml` and `-0050.yaml`. The 25 documents are a subset of the 50 (same seed and ranked
draw), so they pair. In-sample numbers: the 0025 runs tuned the 0050 calibrations, and the 25 new
documents in 0050 are the only held-out check.

| Run | Docs | Gate | Wrong-archive rate | Review rate | Reported spend |
|---|---|---|---|---|---|
| live-smoke-rc11-0025 | 25 | FAIL | 0.565 | ≤ 0.05 | $0.089 |
| live-smoke-rc11-0025-fix1 | 25 | FAIL | 0.591 | 0.083 | $0.094 |
| live-smoke-rc11-0050 | 50 | FAIL | 0.559 | 0.292 | $0.183 |

Bars: quality 0.90 per document, wrong archive ≤ 0.02, review ≤ 0.05. No crashes, no judge errors;
audit trail complete (spans, nodes and archives for every document).

## Review overflow in 0050 is not a judge mistake

HF-034 (`caveat_acceptance_parks`, on for contracts, correspondence and insurance claims) parked 13
documents after two `partial` judge verdicts. Scored with the gate scorer as if archived, 12 of the
13 would have been wrong archives (only one at 0.909). Turning the parks off would raise the
wrong-archive rate to about 0.66. The review rate measures extraction quality below the bar.

The judge is still weak as a retry signal. In `partial` verdicts it named 71 fields: the scorer
confirms 12 as wrong, scores 27 as right, and 32 have no label. So a retry is aimed at the wrong
fields and the second verdict is again `partial`. It also called 9 correspondence documents
`complete` that all scored under 0.90 (mean 0.644), the largest share of the 19 wrong archives.

## Failure points by class (0050, every document scored)

| Class | Correct / scored | Most-missed fields |
|---|---|---|
| contract | 1 / 9 | `cuad_clauses` 7, `parties` 5, `term_length` 5, `payment_terms` 3, `renewal_terms` 3 |
| correspondence | 0 / 15 | `communication_type` 8, `sender` 7, `recipient` 6, `action_items` 4, `intent` 4 |
| insurance_claim | 11 / 16 | `damages_description` 12 (low weight), `supporting_documents` 4 |
| corporate_record | 4 / 7 | `entity_name` 2, `jurisdiction` 2 |

Correspondence misses are mostly label-form conflicts the text cannot settle:

- A recipient is labelled as the top salutation in some messages ("Joanne") and as the full header
  name in others ("Rick Shapiro" under "Rick:", "Forney, John M." under "John -").
- In a sent-mail folder, an unsigned reply's sender is labelled as the mailbox owner, which only the
  folder path shows (`arnold-j/_sent_mail`, `fossum-d/_sent_mail`, `lavorato-j/sent_items`). Models
  never see the path.
- `communication_type` truth is the document's subclass, which labels a letter inside an email as
  `email`, and an email carrying a press release as either.

The correspondence v6 prompt and the schema-guide top-message descriptions moved the 7 paired
documents by at most ±0.08. Label repair comes before another correspondence prompt.

## Order of work

1. Correspondence and contract label audit and repair (near-gold workflow), so later runs measure
   prompts against consistent truth.
2. A contracts prompt aimed at `cuad_clauses`, `parties` and `term_length`, after checking those
   labels can be found in the text.
3. Correspondence prompt (verbatim action items) on the repaired labels; corporate records opt in to
   HF-034.
4. A stronger model for the judge's accuracy check only, measured by flagged-field precision.
