# Corporate gate-scored gaps, calibration split

After the dev round (`v93-20261128-corporate-gate-gaps-dev`), every corporate cell that the production
gate counts and that was still open in slices 100, 250 and 500 sat on a runbook-v2 `heldout` document
(27 documents, 99 cells in slice 500) or a `calibration` document (18 documents, 73 cells). The
playbook forbids labeling `heldout` documents, so this round labels only the 18 calibration
documents. The cells come from `label_eda.py rows --slice slice-0500 --tier gate --presence
unlabeled,disputed_unresolved`, filtered to the calibration split. Each document was read twice,
independently, from its text alone.

Calibration labels are in-sample. The judge reference pool draws from the `calibration` and `pool`
sets, so it now holds these labels. One document (`DOC-f70b11ab7f823e2d`) is new to the pool, which
grows from 119 to 120 corporate documents. A score on calibration documents is reported as
in-sample.

- **Admitted:** 73 near-gold labels on 18 documents (36 populated, 37 documented absences):
  - 62 through `gold_labels.py add --missing-fields` on the 16 documents the catalog already held;
  - 11 through `add` for the 2 documents it did not (`DOC-e1e86caf042eb7b9`, `DOC-f70b11ab7f823e2d`).
- **Settled by:**
  - 64 labels rest on two agreeing passes.
  - A source-reading review (`submissions/corp-gate-cal-mf-review.jsonl` and
    `submissions/corp-gate-cal-new-review.jsonl`) settled the other 9.
  - 7 of the 9 were disputes:
    - `certified_matter` worded three ways on three officer certificates: the label stands, as it
      follows each certification recital.
    - `amended_provisions` on `DOC-a8c0f3d975e591d3`: the label stands. It names each added Article
      XII–XV; the check's last four items were fragments that name no provision.
    - `amended_provisions` on two reverse-split amendments: the check is adopted (`accept_check`).
      The guide asks for one item per provision, the dev round's charter amendments did the same,
      and the label split one provision into two items.
    - `securities_series` on `DOC-27b2d75b3969c033`: the check is adopted. This form supplemental
      indenture names the series it creates ("Series C Convertible Unsecured Subordinated
      Debentures"); only the rate and maturity in its designation are blanks.
  - The other 2 are on `DOC-e12f100d091e15b5`, a subsidiary list whose check pass was a
    byte-identical copy of the label. The reviewer read the whole 797-character exhibit. Each accept
    names the labelled value.
- **Withheld check** (`submissions/corp-gate-cal-withheld-check.jsonl`): that identical copy, which
  the independence guard rightly refuses as a second reading.
- **Agreed, but worth knowing:**
  - `principal_amount` on `DOC-27b2d75b3969c033` is "$130,000,000". The instrument limits the series
    to "not more than US$130 million", and the offering recital is for "US$130 million aggregate
    principal amount".
  - `approval_date` on `DOC-a8c0f3d975e591d3` is 1996-08-08, the shareholder adoption date in
    Article Two. Article Three gives 1996-07-31 (an alternative in both passes).
  - Three `officer_certificate` documents read as certificates of amendment or designation. They
    were labelled against the reviewed subclass, as the brief asks.
- **Still open:** no calibration cell. In slices 100, 250 and 500, every remaining gate gap is on a
  `heldout` document: 29, 57 and 99 cells.

`INDEX.json` lists every file with its sha256 and whether it was an admission input. The `raw-*`
files are the passes as written. The `new-*` and `mf-*` files are what the two `add` calls read: the
raw passes split by whether the catalog held the document, minus the withheld check. The `queue`
and `pass-brief` files are the round's inputs.

These are machine near-gold labels (`use_as_truth: false` in the catalog, not human gold). The
label-repaired release rebuild fills exactly these 73 previously unlabeled cells, and no other cell
changes value, presence, source or rule (`values_moved_by_reviewed_precedence` is empty).
