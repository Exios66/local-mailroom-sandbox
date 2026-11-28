## The brief: corporate_record rc12-p2 labeling pass (Mailroom v9.3, calibration split)

Everything from here down is the text to hand the agent.

You are one independent reading pass in a two-pass near-gold labeling job. Another agent reads
the same documents separately; you never see its work and it never sees yours.

### Paths

- WT     = /home/user/local-mailroom-sandbox   (read-only for you)
- G      = /tmp/claude-0/-home-user/953ae81d-13d8-5e03-8749-6fc95bd18362/scratchpad/rc12/p2
- CORPUS = /tmp/claude-0/-home-user/953ae81d-13d8-5e03-8749-6fc95bd18362/scratchpad/corpus-ff4ca546

### Read first

1. `$WT/docs/gold-labels/LABELING_GUIDE.md`: sections "Ground rules", "Submission format",
   "What the gate checks in a value", "Corporate record fields" and "Long documents". Follow them exactly.
2. `$G/field_briefs.md`: each subclass's fields, with type, definition and where to look
   (written from the Dojo `SUBCLASS_SCHEMAS` and the subclass registry).

### Your input

Each batch directory under `$G/batches/` you are assigned holds `batch.jsonl` (one line per document:
`doc_id`, `subclass`, `fields`, `text_file`, `chars`) and one `DOC-….txt` per document. The `.txt` is
the exact document text the gate checks quotes against. The `subclass` is the reviewed one; label
against it.

Label **exactly the fields listed in that document's `fields`**, nothing else. Core fields
(`entity_name`, `effective_date`, `filing_number`, `signatories`, `jurisdiction`) follow the core
table in the guide's class section. `filing_number` is the official state or SEC file number
printed on the record (a state document number, "File No.", "Commission File Number", an entity
number in a Secretary of State stamp), never an SEC exhibit number. Search the whole text for
"File", "No.", "Number", "Document", "Entity", "Charter" and the Secretary of State certificate
before declaring it absent.

### How to read

- Under about 40,000 characters: read the whole file.
- Longer: read the first 15,000 and last 15,000 characters, then Grep the file for each field's
  anchors (for example indenture: "as Trustee", "Guarantor", "due 20", "aggregate principal amount",
  "Stated Maturity", "mature"; bylaws: "Secretary", "certify", "Amended and Restated", "as of";
  charter amendment: "hereby amended", "adopted", "approved", "formerly", "name of the corporation";
  officer certificate: "certify", "delivered pursuant", "Secretary", "Officer"; rights instrument:
  "Rights Agent", "Exercise Price", "Warrant", "Holder", "Purchase Price"; articles: "Incorporator",
  "Registered Agent", "Resident Agent", "authorized to issue"; POA: "attorney", "appoint", "revoked",
  "expire"). Read the passage around each hit.
- Declare a field absent only after that read or search, and say which in `absent`
  ("not found in full read" / "not found by search").

### Value rules that bite

- Quote evidence verbatim, short (one line or sentence), at most 400 characters (1,500 for list fields).
- Dates `YYYY-MM-DD`; never compute a date that is not stated.
- `principal_amount` and `exercise_price` are currency phrases: a plain dollar figure such as
  "$250,000,000" or "$12.50" for the same stated amount; never convert another currency. If the
  amount is a blank, a bracket placeholder, or ambiguous, leave the field out and explain in
  `supplementary.notes`.
- List fields (`entity_list:*`) are JSON arrays of strings; each item needs a quote that shows it,
  and the list must cover the document, not just the first row.
- Specimen or form documents with blanks (`[•]`, `____`): a blank is not a value. Use `null` with
  `absent` ("form with blank, not found in full read") or leave the field out with a note.
- If unsure between two readings, label the better one and put the other in
  `supplementary.alternatives`.
- `instrument_kind` is exactly one of: `warrant`, `rights plan`, `preferred stock`,
  `registration rights`, `specimen stock` (the schema's list). Never the document title.
- `prior_entity_name`: only when **this** document changes the entity's name (the former name it
  replaces). A former name merely recited in a heading or history is not it: `null`, absent
  "amendment does not change the name", and put the recited name in `alternatives`.
- `approval_date`: the date the board or stockholders adopted the amendment, only when stated.
  A signing or filing date is not it (put it in `alternatives`).
- List fields of free text (`amended_provisions`, `resolutions`): one item per provision, each a
  short verbatim clause that names the provision and its change; the gate scores them by overlap
  with the quotes.
- `trustee`, `securities_series`, `principal_amount`, `maturity_date` for an indenture: the
  operative terms of this instrument. A supplemental indenture that only amends: take the trustee
  from its preamble, and label the series only if the document names it.
- Absent list fields are `[]` (not `null`) with an `absent` reason.

### Output

Write one JSONL line per document of your assigned batches to the output file named in your
assignment, in this shape:

```json
{"doc_id": "DOC-…",
 "labeler": {"model": "claude-sonnet", "role": "<label|check>", "batch": "<batch name from your assignment>"},
 "fields": {"trustee": {"value": "…", "evidence": ["…"]},
            "maturity_date": {"value": null, "absent": "not found by search"}},
 "supplementary": {"doc_class": "corporate_record", "subclass": "<subclass>",
                   "source_read": {"chars": <int>, "complete": <true if you read it all>, "method": "full read | head+tail+search"},
                   "confidence": {"trustee": 0.95}, "alternatives": {}, "notes": ""}}
```

Then validate your file and fix every gate failure it reports (wrong quote, too long, unsupported
date or money) by re-reading the document:

```bash
cd $WT && PYTHONPATH=$WT/src .venv/bin/python -P scripts/gold_labels.py validate \
  --corpus $CORPUS --submissions <your output file>
```

### Rules

- Never read, list or open any other file under `$G/label/` or `$G/check/` except your own output file.
- Never edit anything under `$WT`. Run no network command, and no `sandbox` command.
- Write the output only to the path you were given.
- Finish with a short report: documents done, fields populated, fields absent, fields left out (and
  why), and the final validate summary line.

### Scratch files

Put every script or temporary file only in the private work directory named in your assignment.
Never write, run or read a script elsewhere in the scratchpad (other passes keep theirs there).
