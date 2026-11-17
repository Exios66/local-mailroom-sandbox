# Interim truth label audit and integration handoff

An audit of all 2,682 interim labels that runs use as truth
(`data/labels/interim/`, every label whose `status` is not `disputed`), on corpus
revision `ccd040f6`. It also assesses the three document classes that have no
gold catalog. It is the companion to `verdicts.jsonl`, which covers the gold
catalogs and the disputed interim labels.

## Result

The interim truth set does **not** need a full human review. 96.4% of its
labels are verified, grounded in the text, or differ only in spelling. The
errors cluster in two places, and both have a mechanical fix:

- **Correspondence `recipient` and `sender` gap fills.** 23% of recipients and 9%
  of senders are wrong. The reviewed gold catalog already labels the same
  documents and fields, so the fix is to let gold win (step 2 below), not to
  review them by hand.
- **Merger `effective_date`.** All 23 populated values are the signing date
  (dated-as-of). The gate rule for merger agreements says the field is empty
  when the agreement only defines an Effective Time, which is true of all of
  them. This is a policy decision, not 23 separate reviews.

| Stratum | Labels | Verified | Grounded | Format only | Wrong | Policy | Wrong rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Derived subclass labels (all classes) | 1,036 | 1,030 | 0 | 0 | 6 | 0 | 0.6% |
| Contract corrections (CUAD) | 45 | 45 | 0 | 0 | 0 | 0 | 0.0% |
| Correspondence gap fills: `communication_date` | 235 | 228 | 0 | 0 | 7 | 0 | 3.0% |
| Correspondence gap fills: `recipient` | 230 | 169 | 0 | 6 | 53 | 2 | 23.0% |
| Correspondence gap fills: `sender` | 237 | 158 | 0 | 57 | 22 | 0 | 9.3% |
| Corporate gap fills, reviewed gold to compare | 393 | 382 | 0 | 5 | 5 | 1 | 1.3% |
| Corporate gap fills, no reviewed gold | 413 | 0 | 411 | 1 | 1 | 0 | 0.2% |
| Merger agreement gap fills | 93 | 67 | 0 | 0 | 3 | 23 | 3.2% |
| **Total** | **2,682** | **2,079** | **411** | **69** | **97** | **26** | **3.6%** |

## How each stratum was checked

- **Derived labels (1,036).** Every label was recomputed. Correspondence
  `communication_type` (300) and insurance `cms_source_table` (536) equal the
  Hub subclass. 194 of 200 corporate `record_type` labels equal
  `record_type_for_subclass` of the current Hub subclass. The other six were
  derived from an older subclass that the current Hub and the text both
  contradict: two rights instruments and one set of bylaws are labeled
  `articles_of_incorporation`, two sets of bylaws are labeled
  `powers_of_attorney`, and one Cayman memorandum and articles is labeled
  `other`.
- **Contract corrections (45).** All 32 `parties` lists match the CUAD Parties
  spans. All 13 `effective_date` values equal the CUAD Agreement Date, and CUAD
  marks no Effective Date span in any of them, so the field rule's fallback to
  the dated-as-of date applies.
- **Correspondence and corporate gap fills with reviewed gold (1,095).** Each
  value was compared with the reviewed gold value for the same document and
  field: the text-only value, or the value filled from the original email header
  where gold used it. Every disagreement (172) was read and classified by hand.
- **Corporate gap fills with no reviewed gold (413).** Every populated value was
  found in the document text. Every empty value was checked by scanning the full
  text for the field's anchors; no empty `filing_number` (172) has a file,
  document, registration or charter number in its text. The suspicious empties
  (four certificate-of-designation amendments with no entity name, three rights
  instruments with no signers, one undated amendment) were read: each text
  really lacks the value (the company is only "the Corporation", the signature
  pages are cut off, the date is a blank "[], 2014"). A hand-read sample of 20
  entity names and all 13 filing numbers found one wrong value and one format
  error, both in Delaware filing stamps.
- **Merger agreement gap fills (93).** All 30 documents were read.
  `document_name` (30) and `governing_law` (29) are right. Six of nine
  `effective_time` labels quote the definition; the other three are empty
  although each agreement defines its Effective Time.

## Error kinds

| Kind | Labels | What happened | Recommended action |
| --- | ---: | --- | --- |
| `wrong_message` | 43 | Correspondence value taken from a quoted or forwarded message, or sender and recipient swapped. Gold applies the top-message rule. | Replace with the gold value. |
| `over_inclusive` | 22 | Several addressees or senders in one value; the field takes the first, the rest belong in `additional_recipients`. | Replace with the gold value. |
| `generic_addressee` | 16 | A salutation or list name ("Friends", "ALL", "Customer", "CEO") where gold has the header addressee or no value. | Replace, or clear when gold is empty. |
| `stale_subclass` | 6 | Corporate `record_type` derived from an outdated subclass. | Regenerate from the current Hub subclass. |
| `wrong_value` | 4 | Three corporate dates that disagree with the reviewed gold (two are compiled filings, where gold takes the original record's date), and one Delaware service request number taken as the file number. | Replace. |
| `missed_value` | 4 | Empty although the text has the value: three merger Effective Times and one correspondence sender. | Replace with the text's value. |
| `incomplete_list` | 2 | Corporate signer lists that leave out named signers. | Replace with the gold list. |
| `format_only` | 69 | Same fact, different spelling: a title or email address appended or missing, "Last, First" order, non-ISO dates, a whole filing stamp kept. | Normalize; harmless where the scorer matches names loosely. |
| `policy` | 26 | 23 merger signing dates (see Result) and three labels whose gold is itself still waiting on a policy question in `policy_questions.json`. | The repository owner decides. |

## Classes with no gold catalog

| Class | Documents (train + test) | What the Hub labels | Interim truth | Recommendation |
| --- | --- | --- | --- | --- |
| Insurance claims | 1,100 (986 + 114) | Every key field on every document (`claim_number`, `insurer`, `insured_party`, `policy_number`, `date_of_loss`, `date_filed`, `claimed_amount`, `claim_type`, `coverage_determination`), taken from the source datasets' own structured records. Only three train rows lack a date. | 536 derived `cms_source_table`, all verified. | No gold catalog needed. The labels are source-native, not model-made. A 20-document spot check against the text is enough. |
| Contracts | 600 (540 + 60): 509 CUAD, 91 SEC EDGAR | No key extraction fields. `cuad_clause_labels` holds expert spans for the 509 CUAD documents, including Document Name, Parties, Agreement Date, Effective Date, Governing Law, Expiration Date and Renewal Term. | 45 corrections on 45 documents, all verified. | Build a gold catalog. For the 509 CUAD documents it can be derived mechanically from the CUAD spans, then reviewed only where a span is missing or ambiguous. The 91 SEC EDGAR contracts need extraction plus review. This is the largest unscored gap. |
| Merger agreements | 152 (135 + 17), all MAUD | No key extraction fields; the subclass carries `merger_consideration`. | 93 gap fills on 30 documents. | Build a small gold catalog. `document_name`, `governing_law` and `effective_time` can be extracted from the defined sections and spot-read. Settle the `effective_date` policy first. |

## Files

| File | Contents |
| --- | --- |
| `interim_audit.jsonl` | One line per interim truth label, sorted by class, document and field. |

Each line has `class`, `doc_id`, `field`, `status` (the interim status),
`value` (the interim value), `verdict`, `method`, `action`, and when relevant
`kind`, `reason`, `recommended_value` and `note`.

| `verdict` | Meaning |
| --- | --- |
| `verified` | Checked and right. |
| `grounded` | No reviewed gold exists. The value was found in the text, or its absence was confirmed by an anchor scan; suspicious cases and a sample were read by hand. |
| `format_only` | The same fact as the reviewed value, spelled differently. |
| `wrong` | The value is wrong; `recommended_value` gives the right one, or null to clear it. |
| `policy` | Waiting on a decision by the repository owner. |

| `method` | Check |
| --- | --- |
| `subclass_map` | Recomputed from the current Hub subclass. |
| `cuad_span` | Compared with the Hub's CUAD expert spans. |
| `gold_agree` | Equal to the reviewed gold value. |
| `header_fill_agree` | Empty in the text, but equal to the value gold filled from the original email header. |
| `gold_compare` | Differs from reviewed gold; classified by hand. |
| `text_scan` / `null_scan` | No gold: value found in the text, or anchor scan found no value. |
| `text_read` | Read by hand against the document. |

| `action` | Labels |
| --- | ---: |
| `keep` | 2,490 |
| `replace` | 84 |
| `normalize` | 69 |
| `owner_decides` | 26 |
| `clear` | 7 |
| `regenerate` | 6 |

## Integration steps

For the agent that maintains `data/labels/interim/` and `data/labels/gold/`.
The interim files are built by `scripts/interim_labels.py` and must not be edited
by hand, so each fix goes through the builder or through label precedence.

0. **Never re-review or overwrite the owner's decisions.** The labels in
   `human_reviews.jsonl` are final (see `README.md`). Write their `value` as
   is, and keep them out of any review queue.
1. **Apply `verdicts.jsonl` to the gold catalogs first.** The gold values are the
   `recommended_value` for every correspondence and corporate row here, so gold
   must be final before step 2. Rebuild with `scripts/gold_labels.py` and the
   overlay that production slices read (`data/labels/gold-overlay/`).
2. **Let reviewed gold supersede interim gap fills.** Today a run with
   `dataset.near_gold_labels: true` merges `gold-overlay/` after the interim
   overlay, and an interim truth label wins. That makes the 82 wrong
   correspondence values and 5 wrong corporate values override reviewed gold.
   Either reverse the precedence for fields that reviewed gold labels, or drop
   those gap fills from the interim overlay the way `check --prune` drops
   Hub-superseded ones. This one change resolves every `replace`, `clear` and
   `normalize` row whose `method` is `gold_compare`.
3. **Regenerate the six stale `record_type` labels.** `rederive` will not fix
   them, because it reads each record's own `doc_subclass`, which is the stale
   value. Rebuild those records from the current Hub rows
   (`scripts/interim_labels.py build`, then `check --rows <hub rows> --prune`).
   The `recommended_value` column gives the expected result.
4. **Fix the remaining no-gold labels** through the builder: the three empty
   merger `effective_time` labels (definitions in `recommended_value`) and the
   two Delaware filing numbers (`5673019` and `5673040`). If the builder has no
   override input, dropping the labels is the safe minimum: an unlabeled field
   is not scored, while a wrong one is scored against.
5. **Record the merger `effective_date` decision.** If the gate rule stands,
   drop the 23 signing dates. If signing dates are accepted, amend the rule in
   `config/decisions/` and keep them.
6. **Check and rescore.** Run `scripts/interim_labels.py check`,
   `tests/test_interim_labels.py` and `make check`. Rescore the stored runs that
   used `interim_labels` or `near_gold_labels` before comparing them with new
   runs, since about 100 truth labels change.

## Reproducing

Built from the Hub parquet files at `ccd040f6`, the committed interim and gold
files, and the review in `verdicts.jsonl`. The hand classifications of the 172
disagreements and the merger readings are recorded per label in `kind`,
`reason` and `note`.
