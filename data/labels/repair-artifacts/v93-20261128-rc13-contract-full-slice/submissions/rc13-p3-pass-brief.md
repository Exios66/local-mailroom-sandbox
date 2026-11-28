## The brief: contract rc13-p3 labeling pass (Mailroom v9.3 full slice, dev and calibration splits)

You are one independent reading pass in a two-pass near-gold labeling job. Another agent reads
the same documents separately; you never see its work and it never sees yours.

### Paths

- WT     = /home/user/local-mailroom-sandbox   (repository checkout; read-only for you)
- G      = /tmp/claude-0/-home-user/953ae81d-13d8-5e03-8749-6fc95bd18362/scratchpad/rc13/p3
- CORPUS = /tmp/claude-0/-home-user/953ae81d-13d8-5e03-8749-6fc95bd18362/scratchpad/corpus-ff4ca546

### Read first

1. `$WT/docs/gold-labels/LABELING_GUIDE.md`: sections "Ground rules", "Submission format",
   "What the gate checks in a value", "Contract fields", "Long documents", and, if your batches
   include them, "Correspondence fields" and "Corporate record fields". Follow them exactly.
2. `$G/field_briefs.md`: every field's type, definition, where to look and the catalog's conventions.

### Your input

Each batch directory under `$G/batches/` you are assigned holds `batch.jsonl` (one line per document:
`doc_id`, `subclass`, `fields`, `text_file`, `chars`) and one `DOC-….txt` per document. The `.txt` is
the exact document text the gate checks quotes against.

Label **exactly the fields listed in that document's `fields`**, nothing else. Every document must
get a decision on every listed field: a value with evidence, or `null` (`[]` for list fields) with an
`absent` reason.

### How to read

- Under about 40,000 characters: read the whole file.
- Longer: read the first 15,000 and last 15,000 characters, then Grep the file for each field's
  anchors ("IN WITNESS WHEREOF", "By:", "/s/", "Name:", "dated as of", "Effective Date", "effective",
  "commence", "Term", "expire", "terminate", "notice", "non-renewal", "Territory", "territory",
  "throughout", "fee", "price", "$", "payable", "invoice", "arbitration", "courts of", "jurisdiction",
  "venue"). Read the passage around each hit.
- Declare a field absent only after that read or search, and say which in `absent`
  ("not found in full read" / "not found by search").

### Value rules that bite

- Quote evidence verbatim, short (one line or sentence), at most 400 characters (1,500 for list fields).
  Copy it exactly from the `.txt`, including odd spacing.
- Dates `YYYY-MM-DD`; never compute a date that is not stated (no adding a term to a start date).
- `contract_value`: a plain dollar figure for a stated amount; never sum, convert or annualise.
  If several fees are stated and none is the overall consideration, take the principal fee and
  list the others in `supplementary.alternatives`.
- List fields are JSON arrays of strings; each item needs a quote that shows it, and the list must
  cover the whole document (every party, every signer), not just the first.
- Redacted (`[***]`) or blank (`[•]`, `____`) amounts and dates are not values.
- If unsure between two readings, label the better one and put the other in
  `supplementary.alternatives`.

### Output

Write one JSONL line per document of your assigned batches to the output file named in your
assignment, in this shape:

```json
{"doc_id": "DOC-…",
 "labeler": {"model": "claude-sonnet", "role": "<label|check>", "batch": "<batch name from your assignment>"},
 "fields": {"territory": {"value": "worldwide", "evidence": ["…"]},
            "expiration_date": {"value": null, "absent": "not found by search"}},
 "supplementary": {"doc_class": "<contract|correspondence|corporate_record>", "subclass": "<subclass>",
                   "source_read": {"chars": <int>, "complete": <true if you read it all>, "method": "full read | head+tail+search"},
                   "confidence": {"territory": 0.95}, "alternatives": {}, "notes": ""}}
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
