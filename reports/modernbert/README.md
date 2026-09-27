# ModernBERT training reports (mailroom-ml)

Sandbox-side experiment reports for the **ModernBERT ingest classifier** training
runs in the sibling repo
[`mailroom-ml`](file:///Users/morningstar/Desktop/Cold_Storage/mailroom-ml).
Weights are not vendored here; paths and metrics are pinned from on-disk artifacts
and eval JSON.

| Report | Run | Status |
| --- | --- | --- |
| [RUN-01-MODERNBERT-TRAINING-REPORT.md](./RUN-01-MODERNBERT-TRAINING-REPORT.md) | `20260920-173810` (initial Modal leg) | Archived (checkpoint only) |
| [RUN-02-MODERNBERT-TRAINING-REPORT.md](./RUN-02-MODERNBERT-TRAINING-REPORT.md) | `20260920-214259` → Hub `run2-published` | **Published production bundle** |
| [RUN-02-MODERNBERT-HELDOUT-TEST-REPORT.md](./RUN-02-MODERNBERT-HELDOUT-TEST-REPORT.md) | Run-2 selected checkpoint | Final (trainer test split) |
| [RUN-03-MODERNBERT-TRAINING-REPORT.md](./RUN-03-MODERNBERT-TRAINING-REPORT.md) | Run-3 lineage + **live SSH session** | **Live training in progress** |
| [RUN-03-MODERNBERT-HELDOUT-TEST-REPORT.md](./RUN-03-MODERNBERT-HELDOUT-TEST-REPORT.md) | GPU harness @ 2026-09-21 | Interim until live run completes |
| [eval_run3_20260921.json](./eval_run3_20260921.json) | Full-context eval export | Frozen copy of mailroom-ml report |

**Held-out test set:** 323 documents from
`Lucius-Morningstar/mailroom-modernbert-training` (never used for training,
calibration, or threshold tuning). Training corpus pin `5b72a345…`; canonical
eval corpus `mailroom-dataset @ 46a4d3c2…`.

**Live session (2026-09-27):** Run-3 training is active on the CHTC GPU host via
the operator SSH tunnel. Do not launch competing GPU jobs from this machine until
that session finishes; refresh Run-3 reports from the new checkpoint +
`training/eval_modernbert.py` JSON when training completes.
