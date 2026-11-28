# Gold-label labeling guide

This guide is for the agents that write gold labels for `scripts/gold_labels.py`. It is the
labeler's whole brief. Anything this guide does not cover goes in `supplementary`, never in a
label.

The [near-gold label playbook](NEAR_GOLD_PLAYBOOK.md) covers the round around this guide:
picking targets, dispatching passes, review, admission and advancing labels into production.

## Ground rules

1. **The document's extraction schema comes first.** Each field means exactly what the
   applicable extraction schema and specialist prompt say it means. Corporate records use
   their registered subclass core and entity fields, not the flat core model alone. A label
   must validate against that schema and have a defined scoring role.
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
  phrase (contract `contract_value`, corporate `principal_amount` and `exercise_price`).
  Currency phrases use the plain dollar representation described below when supported by
  the source; never convert another currency. Lists are JSON arrays of strings.
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
  Never use `1_000`, `1e3`, `NaN` or `Infinity`. A currency-phrase field (`contract_value` and merger currency fields) is a
  plain dollar figure the Dojo money scorer parses: `$` and the digits, with commas and cents as
  written ("$250,000", "$400,000.00"). Repeat the phrase as written when it already has that form.
  Otherwise write the same amount in that form: write a scale word out ("$5 million" becomes
  "$5,000,000"), drop a currency code ("US$400,000.00" and "$55,000USD" become "$400,000.00" and
  "$55,000"), and drop a rate ("$40 per month" becomes "$40"). Never compute a total. The quote
  stays the passage as written. For merger fields, the same figure must have a source dollar
  marker (`$`, `US$` or `USD`); a payment word alone is insufficient. Hold a non-US or
  ambiguously qualified dollar amount, an explicit non-dollar amount, or an amount with unknown
  currency: omit the field and explain why in `supplementary.notes`, rather than mark it absent
  or change its currency symbol. Preserve all source qualifiers in the quote and notes. The
  automated check cannot identify every currency qualifier, especially one away from the figure;
  review the surrounding source for currency and hold the field when it is ambiguous.
  `scripts/gold_labels.py check` rejects a `near_gold` phrase that Dojo cannot parse.
- **`party_roles`**: every `"<party>: <role>"` item needs its role word in the quote too
  ("Supplier", "Licensee", plural or defined-term forms are fine); `other` is the only role
  without a word to quote.

## Independent passes

A label becomes `near_gold` when a second, independent agent pass agrees, or when a reviewing
model accepts or corrects it. Record the actual reviewing model; machine review is not human
gold. Independent means the check labeler works from the document alone and never sees the label
pass; the same model family may write both. `build` refuses to run when a file is given as both
`--label` and `--check`, when a submission's `labeler.role` is not `label` (label and override
files) or `check` (check files), or when one document appears twice among the label files,
the check files or the override files. It also refuses a check submission whose `fields` are
byte-identical (sorted JSON) to the label submission's for the same document, and a label and a
check that carry the same `labeler.batch` out of files with the same content: a copy is not a
second reading. When a check is such a copy (common on a record with one fact, such as a single
filing-number stamp), withhold it and have a reviewer read the source for each field: `add`
takes a document without a check pass only when an `accept` or `correct` review settles every
field its label pass holds. Two free-text readings agree only when both or neither are negated ("not",
"no", "never", "without"). Review decisions (below) need a reviewer, and each one must
match a catalog record. A relabel (`--override`) field replaces the earlier label only when it
passes the gate; if it fails, the earlier label stays and the reject goes to the supplementary
store.

## Review decisions

A reviewing model settles a disputed (or single-pass) field with one JSON object per line in a review file (wrapped here for reading):

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
| `accept_check` | adopt the check pass's own entry for this field, quotes and all (write no `entry`; the build takes it from the check submission and gates it). `value_source` is `check_pass` by the check labeler; the verdict stays `accept_check`. The overlay records the actual `reviewer` and uses `near_gold:reviewed_accept_check` (`near_gold:opus_reviewed_accept_check` for an Opus reviewer). |

A corrected or adopted record keeps the label it replaced under `review.original`. The
catalog check (`gold_labels.py check`) requires every `near_gold` record to rest on an agreeing
check pass that passed the gate, or on such a review.

## Adding documents to a built catalog

`gold_labels.py build` rebuilds the whole catalog and needs every label, check, review and
override file the manifest lists in `sources`. `gold_labels.py add` lands the passes for new
documents without them:

```bash
python scripts/gold_labels.py add --corpus DIR --revision SHA \
    --label add-label.jsonl --check add-check.jsonl [--review add-review.jsonl]
```

It runs the same gates as `build` on the new files (roles, independence, the gate on the
corpus text, reconcile, review resolution). A fatal failure (an input or independence refusal,
a document outside the corpus, an unresolved review, or extended stores that fail
`verify_catalog`) writes nothing. A single field that fails the gate is not fatal: the
document's valid fields are committed and the failed one is kept in the supplementary store as
a `gate_reject` row. That document then has a catalog record, so a second `add` for it is
refused and `review` cannot fill the field (it settles existing records only); use
`add --missing-fields` for a corrected independent pass, or a full `build` given every source. Only one `build`, `add` or `review` writes the
stores at a time: a second one is refused untouched and can simply be run again. It also
refuses a document that already has a catalog record (settle those with `review`), a file name
already listed in `sources`, a review line for a document the add does not carry, and a
document with a label pass but no check pass, because a second add could never complete it. The
one exception is a document whose every labelled field a review given to the same `add` settles:
a `correct`, or an `accept` that names the labelled value. The reviewer's source reading is then
the second reading (use it when the check pass was a copy of the label, and withhold the copy).
Existing records are not rewritten. The new records are appended to the catalog and the
supplementary store, which are swapped in together, and the manifest gains the file names under
`sources`, the new hashes and counts, `added_at` and an `additions` entry. The added records
carry `--revision` in their own `schema` binding; the manifest `binding` still describes the
original build.

`add` only appends. A later full `build` must be given every earlier file and the added ones,
or it rebuilds a catalog without the added documents.

### Adding fields a later guide supports

A later pass often fills fields the original target list did not carry (for example corporate
`filing_number`). `add --missing-fields` accepts documents the catalog already holds, but only
for `(doc_id, field)` keys it does not hold:

```bash
python scripts/gold_labels.py add --corpus DIR --revision SHA --missing-fields \
    --label gap-label.jsonl --check gap-check.jsonl
```

Every supplied label, check and review line is checked against the catalog before anything is
written. A key that already has a record refuses the whole add: even when the supplied value
equals the stored one, even when only the check pass carries it, and even when a review rejects
it. Settle an existing record with `review`; never re-add it. The document's class,
`content_sha256`, `doc_sha` and source filename must still match the records already in the
catalog, so fields are never mixed across source texts or classes under one `doc_id`. Schema
revision bindings may differ when that source identity is unchanged. The known corporate or merger subclass must also agree with the current corpus; legacy records without
a subclass binding retain their existing metadata. The add still needs both independent passes for each document.

Existing records and their schema bindings are not rewritten. New rows carry the `--revision`
given to this add, and the manifest's `additions` entry records the opt-in mode and refreshes
`target_fields` to the guide's current list.

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
shouted "URGENT" in a mass mailing is sales pressure, not pressure on the reader. Association,
exchange, club and event mailings to a membership or list are bulk mail too: their opt-in asks
(RSVP, enroll, register, file a claim within 10 days, click to acknowledge) are not action items.
A cancellation ("please disregard"), a permission to stop, a suggestion floated to a group or a
rallying statement is not an action item either. A request in a quoted message that the reader made of someone else is not an action
item of this document, unless the top note hands it to the reader ("Please handle"): then the
quoted concrete asks are the action items (the bare "Please handle" is not one) and their
deadline sets `urgency`. An "ASAP" about the sender's own speed, or an already-answered one in
older quoted mail, is not urgency for the reader. A calendar entry's sender is its chairperson or organiser, and its "Date:" is the
event date, not a send date. A meeting reminder or a standing invitation is `routine`; it is
`time-sensitive` when it asks the reader to do or confirm something today, tomorrow or by a
stated near date. Record any other
message's sender or date in `supplementary.alternatives`.

## Corporate record fields

Source: the pipeline's corporate records specialist prompt and the Dojo corporate schema.

The authoritative subclass definitions are `SUBCLASS_SCHEMAS` and
`corporate_record_json_schema` in the pinned Dojo's `schemas/corporate_record_schema.py`.
The batch includes each assigned entity field's exact description, type and where to look.
Use only its assigned, still-missing fields. Existing near-gold values are protected.
Never replace a subclass fact with a generic summary, a guessed entity or an empty filler.
If evidence is ambiguous or the representation cannot express it, omit the field and retain
the passage and issue in `supplementary`.

| Subclass | Dedicated entity fields | Evidence scope |
| --- | --- | --- |
| `bylaws` | `certifying_officer`, `last_amended_date` | The certifying officer and latest stated amendment/restatement date. |
| `articles_of_incorporation` | `incorporators`, `registered_agent`, `authorized_capital` | Formation signers, service agent and capital article, exactly as written. |
| `certificate_of_formation` | `organizers`, `registered_agent` | Formation signers and service agent; omit `authorized_capital` entirely. |
| `charter_amendment` | `amended_provisions`, `approval_date`, `prior_entity_name` | Each amended provision and actual approval/name-change recitals. |
| `powers_of_attorney` | `principal`, `attorneys_in_fact`, `authority_scope`, `expiration_date` | Grantor, appointed persons, grant clause and stated expiration. |
| `subsidiary_list` | `subsidiaries`, `subsidiary_jurisdictions` | Every listed legal name and distinct jurisdictions as printed; do not substitute one subsidiary's jurisdiction for the parent. |
| `rights_instrument` | `instrument_kind`, `holder`, `rights_agent`, `securities_covered`, `exercise_price` | Instrument title, actual named parties, operative grant and stated price. |
| `indenture` | `trustee`, `guarantors`, `securities_series`, `principal_amount`, `maturity_date` | Actual trustee/guarantors and operative securities terms; distinguish specimen forms. |
| `board_resolution` | `acting_body`, `action_approved`, `resolutions` | Acting body and each actual resolution, preserving conditions and negation. |
| `officer_certificate` | `certifying_officer`, `officer_title`, `certified_matter`, `addressee` | Signing officer, title, certified facts and actual relying party. |
| `other` | Applicable core only | No invented extension fields. |

The shared core fields below apply only where the registered subclass permits them.
In particular, `subsidiary_list` excludes core `signatories`, `jurisdiction` and
`filing_number`; `indenture` excludes `filing_number`. Do not spend label/check work
documenting absence on these inapplicable fields. For an indenture, a permitted core
`jurisdiction` follows the registry's governing-law guidance.

Every populated scalar and every list member needs a short verbatim source quote. Lists
must cover the relevant document content, rather than an arbitrary first row. Keep source
spelling and qualifications; do not calculate new dates, totals or inferred relationships.
The currency-phrase rule above permits formatting the same stated amount as a plain dollar
figure (including expanding a scale word), while preserving the original quote.
An absent applicable field requires a documented source read, and is reported separately
from populated field-level scoring coverage.

| Field | Type | Definition |
|---|---|---|
| `entity_name` | name | The corporation or entity the record is about, full legal name as written. |
| `effective_date` | date | The date the record takes effect, or its adoption or filing date when no effective date is stated. |
| `filing_number` | id | The official filing or document reference number printed on the record (for example an SEC File No. or a state charter/document number), transcribed exactly as written: keep leading zeros and punctuation (`0-1234`, `0012345`). `0` is a stated number. Never use an SEC exhibit number, a form label ("Form 10-K"), a mailing address or the document's year. Null only after the full read (and the long-document search below) finds no official number; when the candidate number is ambiguous, leave the field out and record it in `supplementary` instead of guessing. |
| `signatories` | list of names | People who sign the record (officers, directors, incorporators, grantors), as printed in the execution block. `[]` when there is no execution block. |
| `jurisdiction` | name | The state or country under whose law the entity is organised (for example "Delaware"). |

`entity_name` is the entity the record itself names, not the filer of the EDGAR submission it
came from; null when the record never names it (for example a list of subsidiaries or a power of
attorney that names only the attorney-in-fact). A signatory has signed: an `/s/` or a filled
signature in an execution block. Names typed under blank signature lines, marked `*` as
previously filed, or named only in an opening certification or a notary acknowledgment are not
signatories, so a record nobody signed is `[]`. When no effective, adoption or filing date is
stated, the record's own signing or as-of date is its `effective_date`. A filing that bundles
several records (articles plus later amendments, several powers of attorney) is labelled by its
first record for `effective_date` and `jurisdiction`; `signatories` lists everyone who signs any
of the bundled records, but not a Secretary of State's certifying signature.

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
| `contract_value` | money (text) | Monetary consideration as a plain dollar figure Dojo parses ("$2,000,000"): a scale word written out, no currency code, no rate ("per month"). $0 is a stated amount. Never computed. |
| `dispute_forum` | name | Courts or arbitral seat for disputes, kept separate from governing law. |
| `payment_terms` | free text | How and when the consideration is paid, as stated. |
| `territory` | free text | The stated territory of the grant, distribution or service. |

## Merger agreement fields

The pinned Dojo `MergerAgreementExtraction` v2 and runtime model define these 16 direct
fields. Use only the assigned missing fields and the corpus's observed subclass; never infer
or change the subclass from consideration answers or a submission. An unknown subclass is
held. Do not label derived `merger_consideration` or `maud_clauses`, or inapplicable
`intent`, `subject_matter` or `keywords`. Each populated list member needs its own
supporting quote. Use `[]` or null only after a documented search for an applicable field.

| Field | Type | Definition |
|---|---|---|
| `document_name` | name | Agreement title as stated. |
| `parties` | list of names | All contracting entities as written. |
| `acquirer` | name | Parent acquiring the target, not its merger subsidiary. |
| `target` | name | Target company, not the parent or merger subsidiary. |
| `merger_sub` | list of names | Merger subsidiary or subsidiaries as written. |
| `signatories` | list of names | Persons who actually sign for the parties; do not invent names from blank signature lines. |
| `effective_date` | date | Actual merger Effective Date only, not execution or dated-as-of date. |
| `effective_time` | free text | Stated Effective Time, clock, zone or defined term; distinct from execution and Effective Date. |
| `governing_law` | name | Governing-law sentence, distinct from dispute forum. |
| `per_share_cash_amount` | money (text) | Stated cash per target share, not aggregate equity or debt value. |
| `exchange_ratio` | free text | Stated parent shares per target share. |
| `target_termination_fee` | money (text) | Stated fee payable by target, distinguishing conditions and caps. |
| `parent_termination_fee` | money (text) | Stated reverse termination fee payable by parent, distinguishing conditions and caps. |
| `outside_date` | date | Actual Outside or End Date, distinct from execution and Effective Date. |
| `financial_advisors` | list of names | Financial advisors in brokers and fairness opinion provisions. |
| `legal_counsel` | list of names | Law firms named on notice copy-recipient lines, not financial advisors. |

For money use the plain dollar figure only for a source-supported dollar amount, as in the currency
rule above; never infer a figure, convert currency, calculate a total or choose among ambiguous
conditional fees. Record conditions and caps in supplementary notes and hold a field if one
scalar cannot faithfully represent it. Dates require a complete source calendar date in ISO
form. Although the registry permits relative `outside_date` strings, hold relative or
conditional dates in this pilot. Do not use the agreement's execution or dated-as-of date as
the actual Effective Date without explicit source support. Never fill placeholder people.

For `all_cash`, examine per-share cash; for `all_stock`, the exchange ratio; for
`mixed_cash_stock`, both; for `mixed_cash_stock_election`, the election and both forms; for
`other`, examine the stated terms. These are search priorities, never proof that a blank field
is absent. For long agreements, read the first and last 15,000 characters and conduct an
exhaustive per-field anchor search across the rest, including definitions, consideration,
closing, effective time, termination, fees, advisors and notices. Read surrounding passages,
record ranges searched, and hold ambiguous source evidence in supplementary notes.

## Long documents

Short documents (under about 40,000 characters) are read in full. For a longer one, read the
first 15,000 and the last 15,000 characters in full, then search the rest (Grep on the file)
for each missing field's anchors: execution blocks ("IN WITNESS WHEREOF", "By:", "/s/",
"Name:"), official identifiers ("File No.", "File Number", "Document No.", "charter number"),
dates ("dated as of", "effective", "as of the", "day of"), organisation ("organized
under", "incorporated under", "a Delaware", "State of"), and for contracts "terminate", "notice",
"term", "territory", "fee", "payment", "arbitration", "courts of". Read the passages around each
hit. Declare a field absent only when the full read or this search finds nothing, and say in the
`absent` reason which it was ("not found in full read" or "not found by search").
