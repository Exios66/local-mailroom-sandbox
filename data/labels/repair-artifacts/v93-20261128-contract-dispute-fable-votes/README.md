# Contract dispute executive vote (2026-11-28)

The near-gold contract catalog held 84 records where the label pass and the check pass disagreed
and no review had settled them. The label-repaired release left 78 of those cells blank as
`disputed_unresolved`. This round asked a reviewer from a different model family
(`{"model": "claude-fable", "role": "review"}`) to cast the deciding vote on each one. Its votes
are machine reviews. They are near-gold truth, not human gold.

## What the reviewer saw

- **Disputed fields (84 records on 56 documents):**
  - `payment_terms` 34, `party_roles` 21, `termination_notice_period` 14, `dispute_forum` 4,
    `territory` 3;
  - `agreement_date`, `signatories`, `contract_value` and `expiration_date`, 2 each.
- **Batches:** four, each with the full document text, the label pass's answer and quotes, and
  the check pass's answer and reason. The batches carry document text, so they are not committed.
  [`disputes.jsonl`](disputes.jsonl) holds the same disputes without the text.
- **Instructions:** the [brief](brief.md) points to the labeling guide's ground rules, value gate,
  review decisions and contract field definitions. It asks for a decision on every dispute.
  - The brief is kept as sent. It has one misstatement: it says every `party_roles` item needs its
    role word in a quote. The guide and the gate exempt `other`, which has no word of its own.
  - The votes still used `other` freely: 12 accepts keep it, and 5 corrections name it.
  - The two reviewer fallbacks to `other` below were admitted under the gate's real rule.

## Votes

The raw reviewer output is in [`raw/`](raw), one file per batch:

- 63 `accept` (the label pass was right);
- 21 `correct`: 16 side with the check pass, and 5 combine or narrow the two answers;
- 0 documented absences.

The admitted file is [`review.jsonl`](review.jsonl). It differs from the raw output in three ways:

- **Evidence shape.** The brief asked for evidence as `{"text": ...}` objects. The catalog stores
  plain strings, so each quote was unwrapped. Every quote's text is unchanged and was checked
  verbatim against the corpus text.
- **Two gate fallbacks.** The gate requires a role's word to appear in a quote. On
  `DOC-3f4003eb02433292` and `DOC-4fb6419e37bff201`, the reviewer chose `service_provider` and
  noted that, if the gate refused it, the label's `other` should stand. The gate refused both, so
  these are admitted as `accept` of the label. The note keeps the reviewer's reasoning.
- **One held record.** On `DOC-d87ca3f1c374b83a`, `party_roles`, the reviewer named the franchisor
  `Kiosk Concepts, Inc.`.
  - The source text prints that name with broken spacing (`K iosk  Concep t s ,   I nc .`), so no
    verbatim quote supports the clean name.
  - The label's value, the bare defined term `Franchisor`, is not a party name.
  - The record stays disputed, and [`held_for_owner.jsonl`](held_for_owner.jsonl) keeps the vote.

The command was:

```bash
scripts/gold_labels.py review --corpus <pinned corpus dir> --review review.jsonl
```

It admitted 83 records: 65 `accept` and 18 `correct`.

## Effect on the release

The rebuilt label-repaired release changes exactly the 83 voted cells and no others:

- `disputed_unresolved`: 78 → 1;
- labeled cells: 43,942 → 44,019 (87.5% → 87.6%);
- `needs_human`: 101 → 24. The 24 are 23 reviewed absences over a populated value, plus the held
  record;
- `values_moved_by_reviewed_precedence` stays empty.

## Points to revisit

The reviewer flagged these as judgment calls.

- **`party_roles` kept as `other` where the commercial role has no role word in the text.** This
  covers about nine documents. If the guide later allows cognates such as "Services" for
  `service_provider` or "Purchaser" for `customer`, these should flip to the commercial role.
- **`termination_notice_period` set where the check pass said null.** On a joint filing agreement
  ("revoked … in a signed writing") and an at-will employment letter ("with or without … notice"),
  the stated form of notice was taken as the fact.
- **`DOC-cbc1f0d62edbb23e` `agreement_date`.** The preamble is undated, and the parties signed on
  different days. The later signature date was taken.
- **`DOC-272606d3ac598065` `contract_value`.** The value is a bare `$175`, while the vendor prices
  other services in CAD.
