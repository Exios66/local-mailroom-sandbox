# Gold-label labeling guide

This guide is for the agents that write gold labels for `scripts/gold_labels.py`. It is the
labeler's whole brief. Anything this guide does not cover goes in `supplementary`, never in a
label.

## Ground rules

1. **The pipeline's schema comes first.** Each field means exactly what the pipeline's extraction
   schema and specialist prompt say it means (the definitions below are copied from them).
   A label that would not validate against `schemas.documents.EXTRACTION_SCHEMAS` is useless.
2. **Only label from the text.** Never use the filename, general knowledge or a guess. If the
   document does not state it, the label is the empty value plus an `absent` reason.
3. **Quote your evidence verbatim.** Every non-empty value carries one or more `evidence`
   quotes copied character for character from the document (whitespace may differ). Keep each
   quote short: the smallest span that shows the value, such as one header line or one sentence.
   The gate rejects a quote it cannot find in the document, and a quote longer than 400
   characters, or 1,500 for a list field such as a long cc block ("evidence quote too long"): a whole-document quote would support anything.
4. **Closed labels use the listed tokens only.** Never invent a new token or map one to `other`
   unless `other` is the honest answer.
5. **When unsure, say so.** If two readings are defensible, label the better one and describe
   the other in `supplementary.alternatives`. Never pad a field to look complete.

## Submission format

Write one JSON object per document, one per line (JSONL):

```json
{"doc_id": "DOC-…",
 "labeler": {"model": "<your model>", "role": "label", "batch": "correspondence-020"},
 "fields": {
   "sender": {"value": "Jane Roe, VP Finance, Acme Corp", "evidence": ["From: Jane Roe, VP Finance, Acme Corp"]},
   "communication_date": {"value": "2001-05-14", "evidence": ["Sent: Monday, May 14, 2001 9:02 AM"]},
   "demand_amount": {"value": null, "absent": "no amount is demanded"},
   "urgency": {"value": "routine", "basis": "informational message, no deadline or pressure"}
 },
 "supplementary": {"alternatives": {}, "notes": "", "confidence": {"sender": 0.95}}}
```

- Include every field listed for the document in the batch file, and no other field. The one
  exception is a field you could not decide after reading the whole document: leave it out and
  say why in `supplementary.notes`.
- `value`: the label. Dates are `YYYY-MM-DD`. Money is a number unless the field is a currency
  phrase (contract `contract_value`). Lists are JSON arrays of strings.
- `evidence`: a list of verbatim quotes, each at most 400 characters (1,500 for list fields). Required for every
  non-empty value, except a closed label at its default (correspondence `urgency: routine`),
  which needs a `basis` sentence instead. A closed label that is **not** its default (`urgency`
  other than `routine`) needs at least one quote of three or more words that states the
  pressure, not a single keyword.
- `absent`: required when the value is `null` or `[]`. Say in a few words why ("no addressee:
  press release", "no send date stated").
- `supplementary` (optional, free-form): alternatives, notes, per-field confidence, anything
  else useful later. It is stored apart and never used as ground truth.

## What the gate checks in a value

- **Dates** must be `YYYY-MM-DD` and appear in the quote as a whole date: numeric forms stand
  alone (no digit beside them, so `1/5/2001` is not inside `11/5/2001`; a two-digit year such as
  `5/14/01` counts only for the years 1950 to 2049), and a spelled date must be one date
  expression that holds the month name, the day and the year together ("May 14, 2020",
  "May 14th 2020", "14 May 2020", "14th day of May, 2020"). Only a space, a comma or "day of" /
  "of" may sit between the parts. A time of day or another date in the quote does not support the
  label: "May 14, 2019 ... December 31, 2020" does not support 2020-05-14.
- **Money** is matched on the exact figure, and the quote must show that figure as money:
  a currency marker beside it (`$`, `US$`, `USD`, `dollars`, `€`, `£`) or one of the words
  amount, pay, payment, sum, fee, price, owe, balance or total in the same quote. `$218,440.00`,
  `USD 218,440` and `$2.5 million` support 218440 or 2500000, never a part of the digits;
  "Dated May 14, 2020" supports neither 2020 nor 14. `0` needs a written 0.
  Never use `1_000`, `1e3`, `NaN` or `Infinity`. A currency-phrase field (`contract_value`) must
  repeat the phrase as written in the quote ("$250,000").
- **`party_roles`**: every `"<party>: <role>"` item needs its role word in the quote too
  ("Supplier", "Licensee", plural or defined-term forms are fine); `other` is the only role
  without a word to quote.

## Independent passes

A label becomes `near_gold` when a second, independent agent pass agrees, or when Opus reviews
it. Independent means the check labeler works from the document alone and never sees the label
pass; the same model family may write both. `build` refuses to run when a file is given as both
`--label` and `--check`, when a submission's `labeler.role` is not `label` (label and override
files) or `check` (check files), or when one document appears twice among the label files,
the check files or the override files. It also refuses a check submission whose `fields` are
byte-identical (sorted JSON) to the label submission's for the same document, and a label and a
check that carry the same `labeler.batch` out of files with the same content: a copy is not a
second reading. Two free-text readings agree only when both or neither are negated ("not",
"no", "never", "without"). Review decisions (below) need a reviewer, and each one must
match a catalog record. A relabel (`--override`) field replaces the earlier label only when it
passes the gate; if it fails, the earlier label stays and the reject goes to the supplementary
store.

## Review decisions

Opus settles a disputed (or single-pass) field with one JSON object per line in a review file (wrapped here for reading):

```json
{"doc_id": "DOC-…", "field": "urgency", "verdict": "correct",
 "reviewer": {"model": "claude-opus", "role": "review"},
 "note": "optional reason",
 "entry": {"value": "routine", "basis": "informational message"}}
```

`note` is optional; `entry` is required for `correct` and not used otherwise.
The reviewer needs a non-empty `model` and `role`; a missing verdict, a `correct` without an
`entry`, an unknown verdict or two decisions for one field stop the build.

| Verdict | Effect |
|---|---|
| `accept` | the label stands and becomes `near_gold`. On a field an `--override` relabel replaced, the line must also give `value`, equal to the current label (`{"doc_id": "DOC-…", "field": "sender", "verdict": "accept", "value": "Jane Roe", "reviewer": {…}}`); a stale accept stops the build |
| `reject` | the label is dropped to the supplementary store |
| `correct` | `entry` (`value` and `evidence`, as in a submission) replaces the label; it must pass the gate. `value_source` is `review_correction` by the reviewer |
| `accept_check` | adopt the check pass's own entry for this field, quotes and all (write no `entry`; the build takes it from the check submission and gates it). `value_source` is `check_pass` by the check labeler; the verdict stays `accept_check` and the overlay basis is `near_gold:opus_reviewed_accept_check` |

A corrected or adopted record keeps the label it replaced under `review.original`. The
catalog check (`gold_labels.py check`) requires every `near_gold` record to rest on an agreeing
check pass that passed the gate, or on such a review.

## Correspondence fields

Source: the pipeline's correspondence specialist prompt (`llm/frozen_v1/correspondence_specialist.txt`).

| Field | Type | Definition |
|---|---|---|
| `sender` | name | Who sent it: full name, title and entity as written. Press or wire: the issuing company or media-contact line. Null only when no sender is named. |
| `recipient` | name | The named addressee: the first `To:` entry as printed (a person, a distribution list or a group such as "All Enron Houston"), else a salutation that names a person or a defined group ("Dear GISB Members", "Houston Attendees:"). A generic salutation ("Dear Friends", "Gentlemen", "All", "To Our Readers") is not a named addressee: null. Press releases and wire articles with no named addressee: null. When several people are in "To", put the first one here and the rest in `additional_recipients`. |
| `additional_recipients` | list | Further To, cc'd or copied parties as written. None: `[]`. |
| `communication_date` | date | The date the communication was **sent**, not a deadline, meeting date or invoice date. Null if no send date is stated. |
| `demand_amount` | money | Exact dollars the sender demands the recipient pay (218440.00 for "$218,440.00"). 0 is a stated amount. Null when no amount is demanded **of the recipient**: an amount that is only reported (an invoice total in an internal follow-up, money owed by someone else, an amount the sender will sue a third party for) is not a demand. Never compute or convert. |
| `action_items` | list | At most 3 concrete actions the recipient is asked to take, with deadlines if stated. None: `[]`. |
| `urgency` | label | `routine`, `time-sensitive`, `urgent` or `critical`. Never null. Neutral or unspecified is `routine`. `time-sensitive`: a near deadline or a dated request. `urgent`: stated urgency ("ASAP", "immediately", "urgent"). `critical`: legal, financial or safety consequences stated as imminent. |

Emails often carry forwarded or quoted messages, and the corpus strips each document's own
header, so the message the document *is* often has no header. Take `sender`, `recipient`,
`additional_recipients` and `communication_date` from the **top message**:

- **A reply typed above quoted mail** (a substantive note with no header of its own, above the
  first header): its author (the signature) is the sender and its salutation is the recipient.
  `additional_recipients` is `[]` and `communication_date` is null unless the reply itself
  states them. The quoted message's people and date go in `supplementary.alternatives`.
- **An unsigned top note directly above a "Forwarded by X on `<date>`" stamp**: X is the sender
  and the stamp's date is the send date.
- **A bare forward** (no note, or only "FYI" / "see below"): fall through to the first message
  that has its own header (a `From:` / `To:` / `Sent:` or `Date:` block, or a sender name and
  date line followed by `To:`, as Lotus Notes prints it). A "Forwarded by … on `<date>`" line
  alone is not that header; record the forwarder in `supplementary.alternatives`.

A signature alone ("Thanks, Jim") is not a header, but
when the document has no header at all, the signature's name is the sender. `action_items` and
`urgency` still describe what the document as a whole asks of its reader. A bare pointer ("please see
the attached notice", "check it out") is not an action item; a direct question or request put to
the reader is. Promotional or bulk mail (newsletters, fare alerts, store offers, event
ticket announcements) has no action items: its calls to action are not requests put to the
reader. Its `urgency` is `routine`: an offer deadline ("sale ends June 10"), a countdown or a
shouted "URGENT" in a mass mailing is sales pressure, not pressure on the reader. A request in a quoted message that the reader made of someone else is not an action
item of this document. A calendar entry's sender is its chairperson or organiser, and its "Date:" is the
event date, not a send date. A meeting reminder or a standing invitation is `routine`; it is
`time-sensitive` when it asks the reader to do or confirm something today, tomorrow or by a
stated near date. Record any other
message's sender or date in `supplementary.alternatives`.

## Corporate record fields

Source: the pipeline's corporate records specialist prompt and the Dojo corporate schema.

| Field | Type | Definition |
|---|---|---|
| `entity_name` | name | The corporation or entity the record is about, full legal name as written. |
| `effective_date` | date | The date the record takes effect, or its adoption or filing date when no effective date is stated. |
| `signatories` | list of names | People who sign the record (officers, directors, incorporators, grantors), as printed in the execution block. `[]` when there is no execution block. |
| `jurisdiction` | name | The state or country under whose law the entity is organised (for example "Delaware"). |

## Contract fields

Source: the Dojo contract schema (`cuad_schema.CONTRACT_EXTRACTION_FIELDS`), which defines the
pipeline's `ContractExtraction` v2 fields.

| Field | Type | Definition |
|---|---|---|
| `agreement_date` | date | The "dated as of" or signature date. |
| `expiration_date` | date | End of the initial term when the text states it as a date; else null. |
| `signatories` | list of names | Persons who sign the contract, as printed. |
| `party_roles` | list | One `"<party>: <role>"` line per party. Role is one of `licensor`, `licensee`, `supplier`, `customer`, `distributor`, `reseller`, `franchisor`, `franchisee`, `service_provider`, `client`, `sponsor`, `agent`, `principal`, `partner`, `lender`, `borrower`, `other`. |
| `termination_notice_period` | free text | Notice needed to terminate the contract or to stop a renewal, as stated. |
| `contract_value` | money (text) | Monetary consideration as a plain currency phrase ("$2,000,000"). $0 is a stated amount. Never computed. |
| `dispute_forum` | name | Courts or arbitral seat for disputes, kept separate from governing law. |
| `payment_terms` | free text | How and when the consideration is paid, as stated. |
| `territory` | free text | The stated territory of the grant, distribution or service. |

## Long documents

Short documents (under about 40,000 characters) are read in full. For a longer one, read the
first 15,000 and the last 15,000 characters in full, then search the rest (Grep on the file)
for each missing field's anchors: execution blocks ("IN WITNESS WHEREOF", "By:", "/s/",
"Name:"), dates ("dated as of", "effective", "as of the", "day of"), organisation ("organized
under", "incorporated under", "a Delaware", "State of"), and for contracts "terminate", "notice",
"term", "territory", "fee", "payment", "arbitration", "courts of". Read the passages around each
hit. Declare a field absent only when the full read or this search finds nothing, and say in the
`absent` reason which it was ("not found in full read" or "not found by search").
