# Label review verdicts

A full review of the gold label catalogs and of the interim labels that the
interim set marks `disputed`, on corpus revision `ccd040f6`. The interim labels
that runs use as truth are audited separately in `INTERIM_AUDIT.md`. Each label got one
verdict. Only the labels that need a policy decision are left for a human.

Nothing reads these files by default. They are a record of the review and the
input for applying it to `data/labels/gold/` and `data/labels/interim/`.
`decisions.jsonl` is that input for the gold catalogs.

## Files

| File | Contents |
| --- | --- |
| `verdicts.jsonl` | One line per label: `catalog`, `source` (`gold` or `interim`), `doc_id`, `filename`, `field`, `verdict`, `value` and the evidence for the verdict. |
| `policy_questions.json` | The questions behind each `needs_human` group, keyed by `policy_group`. |
| `human_reviews.jsonl` | The owner's own decisions from the review desk, one line per label. These are final: see below. |
| `interim_audit.jsonl` | One verdict per interim truth label (2,682 labels), with the recommended fix. |
| `INTERIM_AUDIT.md` | The interim truth audit: results by stratum, the classes with no gold catalog, and the integration steps. |
| `decisions.jsonl` | The review as `scripts/gold_labels.py build --review` lines for the correspondence and corporate-record catalogs: 3,069 `accept` (each names the current value) and 173 `correct` (each passes the gate). See below. |
| `decisions_held.jsonl` | The 10 reviewed labels that could not become a decision, each with the reason. |
| `VALIDATION.md` | The validation of the truth labels that production runs score against, before and after the decisions, with the open owner decisions. |
| `interim_reviews.jsonl` | Reviewed interim labels that `scripts/interim_labels.py review` writes into `data/labels/interim/`: 52 correspondence `intent` corrections of wrong Hub values and 1,795 correspondence header fields read from the original email. See below. |
| `contract_value_review.jsonl` | 7 `correct` lines for `scripts/gold_labels.py review`: contract `contract_value` phrases rewritten as plain dollar figures that Dojo parses. They are applied to `data/labels/gold/contract.jsonl`. |

## Verdicts

| `verdict` | Meaning | `value` holds |
| --- | --- | --- |
| `verified` | The label was checked against the document text and is right. | The label as it is. |
| `corrected` | The label was wrong. `previous_value` holds the old value and `note` gives the reason. | The corrected value. |
| `filled_from_original_header` | Correspondence only. The document text does not state the value, so the text-only label is empty. The original email's header (CMU Enron maildir: `X-From`, `X-To`, `X-cc`, `Date`) gives it, and it describes the labeled message. `text_only_value` keeps the text-only label. | The header value. |
| `needs_human` | The guide does not settle the case. `policy_group` names the open question, and `suggestion` (when present) is the alternative value. | The label as it is. |
| `human_verified` | The owner checked the label on the review desk and kept it. `claude_verdict` keeps the verdict before that review. | The label as it is. |
| `human_corrected` | The owner changed the label on the review desk, by choosing the suggestion (`human_suggestion`) or by entering a correction. `previous_value` holds the label before that review. | The owner's value. |

## Counts

| Catalog | Labels | Verified | Corrected | Filled from header | Decided by the owner | Needs a human |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Correspondence (gold, 7 fields) | 6,994 | 5,107 | 169 | 1,666 | 0 | 52 |
| Correspondence `intent` (interim, disputed) | 72 | 46 | 23 | 0 | 0 | 3 |
| Corporate records (gold) | 1,207 | 1,180 | 0 | 0 | 8 | 19 |
| Contracts and merger agreements (interim, disputed) | 13 | 6 | 4 | 0 | 0 | 3 |
| **Total** | **8,286** | **6,339** | **196** | **1,666** | **8** | **77** |

Of the 8 labels the owner decided, 4 were kept and 4 changed (3 to the
suggestion, 1 by a correction). One of the kept labels was one Claude had
already verified.

## Owner decisions are final

`human_reviews.jsonl` is the source of record for decisions the repository
owner made by hand. Each line names the label (`catalog`, `doc_id`, `field`),
the `decision` (`keep`, `use_suggestion`, `correct` or `unsure`), the resulting
`value`, the `label_before_review`, the verdict Claude had given
(`claude_verdict`), the owner's `note` and `reviewed_at`.

- No rebuild, re-review or regeneration may change these labels. Any tool that
  rewrites `verdicts.jsonl` applies `human_reviews.jsonl` last.
  `tests/test_label_review_human.py` fails if a decision is lost or its value
  changed.
- Applying the review to `data/labels/gold/` and `data/labels/interim/` writes
  the owner's value for each of these labels and does not queue them for review
  again.
- A later mark on the review desk for the same label replaces the earlier one;
  `reviewed_at` decides which is newer.
- An `unsure` decision keeps the label in `needs_human`, with the owner's note.

## How each catalog was checked

- **Correspondence (gold).** Every label was read against the document under
  `docs/gold-labels/LABELING_GUIDE.md`, with its rules for the top message.
  Each document was matched to its original email in the CMU Enron maildir. The
  header was used only when it describes the labeled message: a single message,
  a reply typed above quoted mail, or a note above a forward.
- **Correspondence `intent` (interim).** The Hub value and the gate value were
  compared with the message, and the one that fits was kept. When neither fit,
  a third value from the intent vocabulary was used.
- **Corporate records (gold).** For populated labels, each quote was found
  verbatim and checked against the value. For absent labels, the full text was
  searched for the field's anchors. Hits were either other agreements or blank
  dates, so all 283 absent labels stand.
- **Contracts and merger agreements (interim).** Each gate value was compared
  with the document text and with the Hub's CUAD expert spans
  (`cuad_clause_labels`).
  - The four `cuad_clauses` labels are rebuilt from those spans, as
    `Category: first span`.
  - The three `renewal_terms` labels describe renewal by mutual agreement only.
    CUAD marks none of them, so they wait for a policy decision.

## Applying the review to the interim labels

`interim_reviews.jsonl` carries two decisions into `data/labels/interim/`:

- **Hub `intent` corrections.** For 52 correspondence messages, the review found the Hub `intent` wrong. Each line is a `correction` (basis `review_read_message`) with the reviewed value, the `hub_value` it replaces and the review's note. Production then scores those documents against the reviewed value, not the Hub value.
- **Header fields.** For 1,795 correspondence fields, the value comes from the original message's header in the CMU Enron maildir. This covers the 1,666 `filled_from_original_header` verdicts and the 129 `corrected` verdicts whose value the review took from the header (replies typed above quoted mail). For those 129, the header value replaces the reply-rule value that `decisions.jsonl` gives the gold catalog, because the header belongs to the reply itself. Each line quotes the header lines it reads and names the maildir file, and `scripts/interim_labels.py` checks that each name and date is in those lines. These are interim `gap_fill` labels, so they win over the text-only near-gold labels of the same fields.

Apply it with `python scripts/interim_labels.py review`; `check` fails if the file changes without being applied again.

## Contract amounts Dojo can parse

Seven contract `contract_value` near-gold labels were phrases that Dojo's money parser cannot read in full ("$5 million", "$10 million", "US$400,000.00", "$55,000USD", "$40 per month", "$0.05 per Unit"). A correct numeric prediction scored 0.11 to 0.48 against the scale-word and currency-code forms. The rate forms scored 1.0 only through the scorer's text fallback, and the guide leaves the rate out of the amount. `contract_value_review.jsonl` rewrites each as the same amount in plain dollars ("$5,000,000", "$10,000,000", "$400,000.00", "$55,000", "$40", "$0.05") and keeps its quote. `scripts/gold_labels.py review --corpus <dir> --review data/labels/review/contract_value_review.jsonl` applied them in place. The gate checks the corpus text, the catalog `MANIFEST.json` lists the file under `sources.review`, and `gold_labels.py overlay` re-exported the overlay. A later full `build` must include `--review data/labels/review/contract_value_review.jsonl`.

## Applying the review to the gold catalogs

`decisions.jsonl` turns the verdicts on the correspondence and corporate-record catalogs into
review decisions for the gold build:

- A verified label, or a label equal to the owner's value, that is not yet `near_gold` gets
  `accept`, with the current value.
- A corrected label gets `correct`, with verbatim quotes, or an absent reason, that pass the
  gate on the Hub text.
- A header fill keeps its text-only label; the original-header value stays out until the owner
  decides the header policy.
- A label corrected from the original header of a reply typed above quoted mail follows the
  guide's reply rule (signature, salutation, the reply's own "Forwarded by" stamp, else empty)
  instead of the review's `text_only_value`, which kept the quoted message's people for 59 of
  them.
- `needs_human` labels and interim-only labels get no decision.

To apply it, rebuild the catalogs with the original label, check and review passes listed in
`data/labels/gold/MANIFEST.json`, plus `--review data/labels/review/decisions.jsonl`, then
re-export the overlay. `tests/test_label_review_decisions.py` checks, without the Hub, that
every decision matches an unreviewed catalog record, names the current value, keeps the
owner's decisions, and leaves valid `near_gold` records. `VALIDATION.md` gives the effect on
production truth.
