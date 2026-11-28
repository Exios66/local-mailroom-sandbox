# Corporate subclass fields, dev split

The Hub v9.3 rows carry no corporate subclass fields (`trustee`, `registered_agent`,
`authorized_capital`, `certifying_officer`, …). This campaign labels the missing salient fields of
135 dev-split corporate documents from the text alone, with two independent passes per document.

- **Admitted:** 457 near-gold labels on 131 documents (253 populated, 204 documented absences):
  - 413 fill missing fields on 120 documents the catalog already held;
  - 44 are on 11 new documents.
- **Settled by:** 409 labels rest on two agreeing passes. The other 48 disputes were settled by a
  source-reading review, recorded in `submissions/corp-subclass-dev-review-*.jsonl`:
  - 34 accepted the label;
  - 6 adopted the check pass;
  - 8 corrected the label. Five `prior_entity_name` values only recited a former name, so they
    are null; a reverse-split provision is now one item; a scheduled-holder field and an unnamed
    warrant series are null.
- **Held out:**
  - 4 documents whose passes were byte-identical (the independence guard refuses them);
  - the 20 documents whose reviewed subclass differs from the Hub subclass.

`INDEX.json` lists every file with its sha256 and whether it was an admission input. The
`raw-label` / `raw-check` files are the passes as written, and the `admitted-*` files are the
inputs `gold_labels.py add` read. One label pass for group g05 is withdrawn
(`corp-subclass-dev-g05-withdrawn-label.jsonl`): it ran a shared scratch script that wrote the
g05 check output, so it may have seen the check. A fresh pass relabeled g05.

These are machine near-gold labels (`use_as_truth: false` in the catalog, not human gold). They
reach production scoring through the label-repaired release and the staged overlay. That release
now targets each corporate document's subclass fields (see its README).
