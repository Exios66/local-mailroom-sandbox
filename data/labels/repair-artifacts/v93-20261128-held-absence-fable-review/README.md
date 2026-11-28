# Held near-gold absence review (2026-11-28)

The label-repaired release held 23 cells for administrative review before promotion. In each one,
an earlier review recorded the field as absent, while another source held a populated value. The
release marks such a cell `needs_human`. This round asked two independent reviewers
(`{"model": "claude-fable", "role": "review"}`, passes A and B) to read the source text of every
held cell. Neither saw the other's answers. Their votes are machine reviews: near-gold truth, never
human gold.

## What the reviewers saw

- **Held cells (23):** [`queue.jsonl`](queue.jsonl) lists them without document text.
  - `entity_name` 13, each against the official `hub_v9.3` name;
  - `agreement_date` 9, against a rule match (8) or a value derived from the Hub (1);
  - `jurisdiction` 1, against a rule match.
  - 13 absences came from the interim layer and 10 from the near-gold catalog.
- **Packets:** one per cell, with the full document text, the earlier reviewer's reason and every
  competing value. The packets carry document text, so they are not committed.
- **Instructions:** the [brief](brief.md) points to the labeling guide's ground rules, value gate,
  review decisions and the corporate and contract field definitions. It asks for a decision on every
  cell, and it says a name or date found only in filing metadata, or only by inference, is absent.

The held `party_roles` record on `DOC-d87ca3f1c374b83a` (Kiosk Concepts) was not sent. It is a
disputed record, not a reviewed absence, and it stays with the owner as
[the contract dispute vote](../v93-20261128-contract-dispute-fable-votes/README.md) describes.

## Votes

The raw output is in [`raw/`](raw), one file per reviewer.

- **Agreement:** the two reviewers gave the same verdict and value on all 23 cells; none split.
- **22 absences stand.**
  - On the 13 `entity_name` cells, the Hub's name is the EDGAR filer, and the record never writes
    it.
    - The record calls the entity only "the Corporation" or "the Registrant".
    - On a subsidiary list, the filer's name appears only inside subsidiary names.
    - A power of attorney names its signers and attorney-in-fact, but no company.
  - On the 9 `agreement_date` cells, the dates in the text belong to something else: a cited
    earlier agreement, a press-release dateline or a filing. Or the form's own date is a blank
    placeholder such as "dated as of , 2007".
- **One value is stated in the text.** On `DOC-971bbacf86cd7a94`, the governing-law clause reads
  "GOVERNED BY AND CONSTRUED IN ACCORDANCE WITH THE LAWS OF THE STATE OF NEW YORK", so its
  `jurisdiction` is `New York`.

## What was admitted

[`review.jsonl`](review.jsonl) holds the one correction. It supersedes the earlier `accept` of a
null value. The command was:

```bash
scripts/gold_labels.py review --corpus <pinned corpus dir> --review review.jsonl
```

It admitted one `correct` record.

The 22 standing absences are not re-recorded. In the release, a reviewed absence over a populated
value stays `needs_human` until an `owner_review` clears it, and a machine vote cannot. Instead,
[`concurrence_for_owner.jsonl`](concurrence_for_owner.jsonl) gives the owner one line per cell for
sign-off:

- the competing value;
- both reviewers' reasons;
- an empty `owner_signoff`.

## Effect on the release

The rebuilt label-repaired release changes only the corrected cell:

- the `jurisdiction` cell goes from a reviewed absence to `New York`. The labeled count does not move,
  because a reviewed absence already counts as labeled;
- `needs_human`: 24 → 23. The 23 are the 22 reviewed absences above, plus the held Kiosk record;
- `values_moved_by_reviewed_precedence` stays empty.

[`INDEX.json`](INDEX.json) records the counts and each artifact's sha256.
