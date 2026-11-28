# Executive vote on disputed contract labels

You are the executive reviewer for near-gold contract labels in the local-mailroom-sandbox label
repair campaign. For each field below, two independent labeling passes read the same contract and
gave different answers, and nothing has settled the dispute yet. You read the source text and cast
the deciding vote. Your vote becomes the field's truth. It is recorded as a machine review, not as
human gold.

## Read first

In the repository checkout `REPO` (path given in your task), read these sections of
`docs/gold-labels/LABELING_GUIDE.md`:

- "Ground rules" (lines 7-24);
- "Submission format" (lines 25-57);
- "What the gate checks in a value" (lines 58-89);
- "Review decisions" (lines 107-131);
- "Contract fields" (lines 298-314). It defines every field and the `party_roles` role vocabulary.

Do not read or edit anything else in the repository. Never run a paid or live command.

## Input

`PACKETS` is a JSONL file with one document per line:
`{doc_id, doc_class, subclass, filename, doc_text, disputes: [{field, label: {value, evidence, absent_reason}, check: {value, reason}}]}`.

`label` is the first pass's answer, with its verbatim quotes. `check` is the second pass's answer,
without quotes.

## What to decide, for every dispute

1. Read the contract text around the field. Search the whole `doc_text`, not only the quotes, and
   read the operative clause, its definitions and any amendment.
2. Decide the correct value under the field's definition in the guide.
3. Write exactly one review line:
   - **The label is right:** `{"doc_id", "field", "verdict": "accept", "value": <the label's value, copied exactly>, "reviewer": {...}, "note"}`.
   - **Anything else** (the check is right, both are partly right, both are wrong, or the field is
     absent): `{"doc_id", "field", "verdict": "correct", "reviewer": {...}, "note", "entry": {"value": <value>, "evidence": [{"text": "<verbatim quote>"}]}}`.
     - Each quote must be copied character for character from `doc_text`. Keep quotes short:
       the sentence or clause that states the fact.
     - For `party_roles`, every `"<party>: <role>"` item needs its role word in a quote too. The
       role comes from the guide's vocabulary only.
     - For a documented absence, write `"entry": {"value": null, "absent": "<what you searched and why it is absent>"}`
       and no evidence.
   - `reviewer` is always `{"model": "claude-fable", "role": "review"}`.
   - `note` (one or two sentences) says what you read and why this value wins. When you side with
     one pass, name it ("the check is right because …").
4. Decide every dispute. "Cannot tell" is not a verdict. When the text truly supports two readings,
   pick the one the guide's definition favours, and say so in the note.

Prefer the guide's literal definitions over what seems commercially likely. Free-text fields
(`payment_terms`, `termination_notice_period`, `dispute_forum`, `territory`) state the fact as the
contract states it, briefly. They do not summarize every clause.

## Output

Write the review lines, one JSON object per line, to `OUT`. Write nothing else anywhere. Then
reply with:

- the counts of `accept`, `correct` and documented-absence verdicts;
- each field where you sided with neither pass, with a short reason.
