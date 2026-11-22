# Label validation for the Dojo, the Mailroom pipeline and production runs

This is a check of the truth labels that a production slice scores against, on corpus revision
`ccd040f6`. It covers 3,302 Hub documents: 2,979 train and 323 test. It was run on `main` at
#323, which brought the contract gold catalog and the revised overlays. Labels were taken as
production assembles them:

1. Hub ground truth.
2. The interim overlay (`data/labels/interim/`).
3. The near-gold overlay (`data/labels/gold-overlay/`), which fills only fields that nothing
   else labels.

Each check was run twice: once on the committed overlays, and once with `decisions.jsonl`
applied to the gold catalogs in memory. The second run uses `gl.apply_review`, then
`gl.overlay_records`. The committed near-gold overlay equals
`overlay_records(catalog)` for all 950 documents, so this simulation starts from the same
labels that runs use today.

## Overall assessment: share with caveats

The near-gold layer is ready once `decisions.jsonl` is built into the catalogs:

- Every near-gold label passes the pipeline's pydantic schema and the Dojo field types.
- Every label is grounded in the current document text.
- Every label agrees with the review, apart from one held label.

Three problems remained, and each needed a decision from the owner before the overlays could change
(see the caveats below):

- the interim overlay wins over reviewed gold;
- 52 Hub `intent` values are wrong;
- six contract amounts are written in a form that Dojo cannot score.

### Resolved since this validation

The owner decided issues 2, 3 and 6, and delegated issues 1, 4 and 5 and the open policy
questions to Claude on 2026-11-18. The fixes are committed:

- **Issue 2.** The 52 wrong Hub `intent` values are interim `correction` labels (basis
  `review_read_message`) from `interim_reviews.jsonl`.
- **Issue 6.** Correspondence header fields take the original email header. 1,795 interim
  `gap_fill` labels (basis `original_header`) from `interim_reviews.jsonl` quote the maildir
  header lines. They replace 329 gate gap fills (315 of them with a different value) and win over the text-only
  near-gold labels of the same fields. This also covers 45 of the 82 audit "wrong"
  correspondence values in issue 1.
- **Issue 3.** The contract amounts are plain dollar figures that Dojo parses. The new catalog
  check found a seventh one ("$0.05 per Unit"), so `contract_value_review.jsonl` corrects 7
  near-gold labels. Each one now scores 1.0 against itself.

- **Issue 1.** Reviewed gold supersedes the interim gap fills it contradicts.
  `scripts/interim_labels.py check` reports a gate `gap_fill` whose value the near-gold overlay
  labels otherwise for the same text, `check --prune` drops it and `build` drops it on every
  rebuild, so near-gold fills the field. With the decisions applied, 111 gap fills went: 99
  correspondence (66 `sender`, 32 `recipient`, 1 `communication_date`) and 12 corporate
  (7 `effective_date`, 5 `signatories`). 43 of them (32 correspondence, 11 corporate)
  disagree beyond format; the other 68 differ only in form ("Travis C. McCullough" against
  "Travis C. McCullough, Enron North America Corp."). Each one is a truth value that changes,
  because the Hub labels none of these fields. The 1,763 reviewed `original_header` labels that
  differ from the text-only gold are kept (issue 6); `check` notes them. The 3 merger values
  have no gold catalog and stay with `INTERIM_AUDIT.md` steps 4 and 5.
- **Issue 4.** All held and `needs_human` labels were decided by consensus: three independent
  readings per label (Claude and two fresh subagents), majority value wins, a three-way split
  stays open. Each vote is in `consensus_votes.jsonl`, each group's rule and tally in
  `policy_questions.json` (`decision`, `decided_by`, `consensus`). Of 87 labels (71 gold and
  6 interim `needs_human`, 10 held), 68 were unanimous, 17 were 2-1 and 2 split. The 2 splits
  stay open: DOC-4e56f772d524639c `action_items` (`needs_human`) and DOC-6e5eb0c3089badbc
  `action_items` (held, its earlier review stands). Where an earlier review had settled the record
  (7 held labels, 3 `soft` and 1 `urgency` label), the change is a line in
  `decisions_supersede.jsonl` that names the review it replaces; the rest are ordinary
  decisions.
- **Issue 5.** The 44 corporate `entity_name` values are interim `correction` labels (new basis
  `review_read_record`) in `interim_reviews.jsonl`, decided by the same vote (42 unanimous,
  2 at 2-1). 31 name the entity the exhibit states, with a quote ("Electric City Corp." on the
  LIME ENERGY certificates); 13 are null, where the record names no entity (subsidiary lists,
  powers of attorney). They replace the Hub value, kept as `hub_value`.

**Caveat:** the header values are not in the corpus text. An extraction from that text cannot find
them, so scores on those fields drop until mailroom-dataset restores the headers.

## What changed when the decisions were applied

The "With the decisions" column is this validation's in-memory forecast; "Applied" is the
committed overlay after `scripts/gold_labels.py review` (2026-11-18).

| Near-gold truth | Before | With the decisions | Applied |
| --- | ---: | ---: | ---: |
| Documents in the overlay | 950 | 1,534 | 1,535 |
| Labels in the overlay | 5,843 | 9,041 | 9,101 |
| Correspondence labels in the overlay | 4,256 | 6,253 | 6,994 |
| Corporate-record labels in the overlay | 75 | 799 | 1,207 |
| Contract labels in the overlay (not reviewed here) | 900 | 900 | 900 |
| Reviewed labels left unused as single-pass candidates | 2,652 | 1 | 0 |

Reconciliation note (added 2026-11-20): only the "Applied" column sums from its class rows
(6,994 + 1,207 + 900 = 9,101). The "Before" and "With the decisions" totals (5,843 and 9,041)
come from that run's overall counter, and their three class rows leave 612 and 1,089 labels
unattributed. That run did not keep per-class counters for the remainder, so the gap cannot be
recomputed now. Treat those two class breakdowns as partial and the totals as the run's figures.

Every correspondence and corporate-record catalog record is now `near_gold`. Four catalog
values differ from their verdict: the split held label DOC-6e5eb0c3089badbc `action_items`,
and three reply-rule labels whose accepted value is the header reading while the verdict's
`text_only_value` is empty or shorter (DOC-2ccf94f14bd5f040 and DOC-d3d85dc1b1514bec
`additional_recipients`, DOC-39f0bf8b666ffa71 `recipient`).

The decisions contain 3,088 `accept` and 216 `correct` lines (3,069 and 173 before the
consensus review), and no `reject` lines (the four owner `signatories` decisions are already
in the catalog, from #336). `decisions_supersede.jsonl` adds 11 `correct` lines that replace
an earlier review they name. They were keyed to the catalogs exactly as `main` had them:

- Each `accept` names the current value, as the gate on `main` requires.
- Each `correct` passes `validate_submission` on the Hub text.
- The owner's own desk decisions are carried as decided.

`tests/test_label_review_decisions.py` checks, without the Hub, that each one is applied to
its catalog record. Ten labels were held in `decisions_held.jsonl`; one is left:

- 8 belonged to records that an earlier review decision already settled. A line in
  `decisions_supersede.jsonl` now names that review and replaces it for 7 of them; the vote on
  DOC-6e5eb0c3089badbc `action_items` split, so it stays held.
- 1 `action_items` correction failed the gate; the vote kept the fuller wording, which the
  gate supports.
- 1 sender had no verbatim quote; the vote took the two signature lines, quoted as written.

### The reply rule

129 correspondence labels were corrected from the original email header, in documents where a
reply is typed above quoted mail. For these, the review's `text_only_value` was not
consistent: 59 kept the quoted message's people. The decisions apply `LABELING_GUIDE.md`
instead:

- The reply's signature is the sender, and its salutation is the recipient.
- An unsigned note above a "Forwarded by X on <date>" stamp takes X and that date.
- Anything the reply does not state is null or `[]`.
- A bare forward falls through to the quoted header.

The result is 23 stated values and 98 empty values, all with quotes or an absent reason that
the gate accepts. These 121 are the lines in `decisions.jsonl` whose note records the reply rule
("reply typed above quoted mail"). The other 8 of the 129 are not recorded under that note, so
this report cannot attribute them (checked 2026-11-20). Of the 23 stated values:

- 15 are signatures or salutations ("Jim", "Kay", "Anita", "mhc").
- 8 come from the reply's own forward stamp ("Sally Beck", 2000-01-28).

One name appears only as an invitee of the quoted meeting (DOC-79b329d55d8c0e6f `sender`), so
that field is empty.

## Methodology review

- **Population.** All Hub rows, both splits, with the effective truth per field. Hub template
  keys that `gl.hub_labels` does not count as labels are excluded.
- **Checks per label:**
  - The document is in the Hub, its text sha256 matches, and its class matches.
  - The value fits its Dojo field type: ISO date, money, entity list, or closed vocabulary.
  - It validates against the Mailroom pydantic field annotation.
  - Dates are present in the text, and names reach at least 60% token coverage.
  - It agrees with the review (`verdicts.jsonl`, `interim_audit.jsonl`).
  - Dojo gives the label a full score against itself, and money also against its plain number.
- **Comparison rule.** Header fills are compared with their text-only reading, because header
  values are still a pending owner policy. Reply-rule labels are compared with the decision.
  Values are compared after `gl._canon`. Values that differ in raw form but that
  `gl.values_agree` matches count as format-only.

## Issues found

1. **[High, resolved: reviewed gold supersedes] Interim gap fills override reviewed gold.** In this order, interim values win over
   reviewed near-gold:

   | Class | Disagreements with the review | Audit "wrong" values still used as truth | Reply-rule labels the interim layer holds back |
   | --- | ---: | ---: | ---: |
   | Correspondence | 64 | 82 | 14 |
   | Corporate records | 9 | 6 | 0 |
   | Merger agreements | 0 | 3 | 0 |

   The interim builder has no override input, so only a change of precedence can fix this.
   That change is step 2 of `INTERIM_AUDIT.md`: reviewed gold supersedes interim gap fills.
   The alternative is a new interim gate run. **Owner decision.**
2. **[High, resolved] 52 Hub `intent` labels on correspondence are wrong.** The review found them wrong,
   and the disputed interim intents that would correct them are not applied. They need
   interim corrections. **Owner decision** on whether the interim set may carry corrections
   of Hub values.
3. **[Medium, resolved: 7 rewritten] Six contract `contract_value` labels that Dojo cannot score fully.** These are
   near-gold, from #323:
   - DOC-11d813797d4c1723 and DOC-10357f1d86b3081e: "$5 million"
   - DOC-589f96335e2a27da: "$10 million"
   - DOC-d417cfb343d5bf46: "US$400,000.00"
   - DOC-24cf2e7be333c3b3: "$55,000USD"
   - DOC-8df9af6d65f3a2eb: "$40 per month"

   A correct prediction scores below 1. For example, `5000000` scores 0.125 against
   "$5 million", and "$5,000,000" scores 0.33. The guide says to copy the currency phrase and
   never compute it. The choice is between normalising these six labels and teaching the
   scorer word multipliers and currency prefixes. A per-month fee may also be payment terms
   rather than a contract value. **Decided:** the labels were normalised to plain dollar figures,
   with the rate left out of the amount (see "Resolved since this validation").
4. **[Medium, resolved: consensus vote] Ten review labels are held** (see above). Seventy-one
   other labels wait in `needs_human`, grouped by question in `policy_questions.json`.
5. **[Medium, resolved: 44 interim corrections] 44 Hub corporate `entity_name` values are not in the text.** They reach
   0–50% token coverage. They are the EDGAR filer name rather than a name the exhibit states.
   For example, "LIME ENERGY CO." is on a certificate that amends Electric City Corp. Hub
   truth, not reviewed here.
6. **[Medium, resolved: header values adopted] The header-fill policy is still open.** Under the text-only reading, 1,358
   near-gold correspondence labels agree with the review, and the original header would add a
   value to them. The decisions keep the text-only labels.
7. **[Low] Format only, and Dojo parses all of it:**
   - 4 interim corporate `effective_date` values are not ISO ("June 1, 2013").
   - 6 Hub insurance dates are "N/A", which Dojo treats as absent.
   - The Hub stores 4,750 lists and 950 insurance amounts as strings, and Dojo parses them
     before scoring.
8. **[Low] One interim contract `effective_date` is not in the text:** DOC-d6b6b418dd211b76,
   2017-03-27.

## Calculation spot-checks

- Counting the same labels two ways gives the same totals. The overlay simulation counts
  1,190 corporate-record and 6,951 correspondence near-gold records. The decisions add
  1,083 corporate and 2,163 correspondence decisions.
- The decisions and the human rows line up:
  - all 8 owner decisions are carried with the owner's value;
  - none is rejected;
  - no label has two decisions.
- Applying every decision with `gl.apply_review` leaves 0 near-gold problems in the
  catalogs.
- Dojo self-scores: 26,507 of 26,513 non-empty scored truth labels get 1.0, including their
  number form. The 6 exceptions are issue 3.
- Every overlay document is in the Hub at the same text sha256 and the same class: 1,111
  interim documents and 1,534 near-gold documents.

## Visualization review

There are no charts. The tables above count labels, not documents, unless a row says
otherwise.

## Required caveats

- Near-gold labels are Claude-reviewed and not human gold. `use_as_truth` stays false, and
  the floor viewer reports them as their own tier.
- Header values from the original emails are interim `original_header` labels (issue 6), not
  gold decisions. They win over the text-only gold labels of the same fields at run time.
- Contract near-gold labels (#323) were checked for schema, Dojo type and scorability only.
  They were not re-read against the documents.
- The decisions were applied in place with `scripts/gold_labels.py review --corpus <dir>
  --review data/labels/review/decisions.jsonl data/labels/review/decisions_supersede.jsonl`,
  on the Hub text at `bc9eab28` (every catalog `doc_sha` matches it; `ccd040f6` is not in the
  local cache). A later full `build` needs the original label, check and review passes listed
  in `data/labels/gold/MANIFEST.json`, which are not in the repository, plus these two files.
- Policy and held labels were decided by Claude under the owner's delegation, by majority of
  three independent readings, not by a human.
