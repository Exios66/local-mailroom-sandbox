# Administrative review of held near-gold absences

You are one of two independent executive reviewers for the local-mailroom-sandbox label repair
campaign. The other reviewer reads the same cells, and you do not see each other's answers.

Each cell below is held for administrative review before its label is promoted to production
truth. An earlier review recorded the field as **absent** in this document, but another source
holds a populated value:

- `hub_v9.3`: the official dataset label. It may come from EDGAR filing metadata rather than the
  document text.
- `generated_rule`: a verbatim pattern match in the text.
- `generated_derived`: a value computed from the Hub.

You decide which one is the document's truth. Your vote is recorded as a machine review, not as
human gold.

## Read first

In the repository checkout `REPO` (path given in your task), read these sections of
`docs/gold-labels/LABELING_GUIDE.md`:

- "Ground rules" (lines 7-24);
- "What the gate checks in a value" (lines 58-89);
- "Review decisions" (lines 107-131);
- "Corporate record fields" (lines 239-297), especially the `entity_name` and `jurisdiction`
  rows and the note after the table, which says `entity_name` is the entity the record itself
  names, not the EDGAR filer;
- "Contract fields" (lines 298-314), for `agreement_date`.

Do not read or edit anything else in the repository. Never run a paid or live command.

## Input

`PACKETS` is a JSONL file with one held cell per line. Each line holds `doc_id`, `doc_class`,
`subclass`, `filename`, `field`, `reviewed_absence`, `populated_alternatives` and `doc_text`.

- `reviewed_absence` has `{layer, reason, reviewer, status}`. Its `reason` is the earlier
  reviewer's own explanation.
- `populated_alternatives` lists each competing value, as `[{source, value}]`.

## What to decide, for every cell

1. Read the whole `doc_text`. Search for the field's fact everywhere: headings, the preamble,
   recitals, signature blocks, stamps and certifications. Do not stop at the earlier reviewer's
   reason.
2. Apply the guide's definition literally. A value is truth only if the document text states it.
   A name or date that appears only in filing metadata, or only by inference, is absent here.
   - For `agreement_date`, a date the document gives for something else does not count (an
     exhibit date, a filing date, a date in a cited earlier agreement, a placeholder like
     `[  ], 2006`).
   - For `entity_name`, the entity has to be named in the record. "The Corporation" or
     "the Registrant" alone does not name it.
3. Write exactly one line per cell:
   - **The absence is right:**
     `{"doc_id", "field", "verdict": "absent", "reason": "<what you searched and why no value stands>"}`.
   - **A value is stated in the text:**
     `{"doc_id", "field", "verdict": "populated", "value": <value>, "evidence": ["<verbatim quote>", ...], "reason": "<why>"}`.
     - Dates are ISO `YYYY-MM-DD`.
     - Names are the full legal name as written.
     - Each quote is copied character for character from `doc_text`, kept short, and contains
       the value's own words or date.
     - The value may differ from every listed alternative if the text states another one.
4. Decide every cell. "Cannot tell" is not a verdict. When two readings are possible, pick the
   one the guide's literal definition favours, and say so in `reason`.

## Output

Write the lines, one JSON object per line, to `OUT`. Write nothing else anywhere. Then reply with:

- the counts of `absent` and `populated`;
- every cell where your value differs from all of the listed alternatives.
