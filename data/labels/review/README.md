# Label review verdicts

A full review of the gold label catalogs and of the interim labels that the
interim set marks `disputed`, on corpus revision `ccd040f6`. Each label got one
verdict. Only the labels that need a policy decision are left for a human.

Nothing reads these files by default. They are a record of the review and the
input for applying it to `data/labels/gold/` and `data/labels/interim/`.

## Files

| File | Contents |
| --- | --- |
| `verdicts.jsonl` | One line per label: `catalog`, `source` (`gold` or `interim`), `doc_id`, `filename`, `field`, `verdict`, `value` and the evidence for the verdict. |
| `policy_questions.json` | The questions behind each `needs_human` group, keyed by `policy_group`. |

## Verdicts

| `verdict` | Meaning | `value` holds |
| --- | --- | --- |
| `verified` | The label was checked against the document text and is right. | The label as it is. |
| `corrected` | The label was wrong. `previous_value` holds the old value and `note` gives the reason. | The corrected value. |
| `filled_from_original_header` | Correspondence only. The document text does not state the value, so the text-only label is empty. The original email's header (CMU Enron maildir: `X-From`, `X-To`, `X-cc`, `Date`) gives it, and it describes the labeled message. `text_only_value` keeps the text-only label. | The header value. |
| `needs_human` | The guide does not settle the case. `policy_group` names the open question, and `suggestion` (when present) is the alternative value. | The label as it is. |

## Counts

| Catalog | Labels | Verified | Corrected | Filled from header | Needs a human |
| --- | ---: | ---: | ---: | ---: | ---: |
| Correspondence (gold, 7 fields) | 6,994 | 5,107 | 169 | 1,666 | 52 |
| Correspondence `intent` (interim, disputed) | 72 | 46 | 23 | 0 | 3 |
| Corporate records (gold) | 1,207 | 1,181 | 0 | 0 | 26 |
| Contracts and merger agreements (interim, disputed) | 13 | 6 | 4 | 0 | 3 |
| **Total** | **8,286** | **6,340** | **196** | **1,666** | **84** |

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
