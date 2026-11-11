# Floor replay sample

A small, pinned sample of the public core corpus plus a **scripted** pipeline trace,
so `sandbox floor` can be viewed and debugged on a machine with no run store.

## What is here

`runtime/runs/replay-mailroom-sample/`

- `dataset.jsonl` — 120 docs, 24 per live class, drawn from
  `Lucius-Morningstar/mailroom-dataset` config `ground_truth` at revision
  `bc9eab280044befb51e19dda3071d290a8677f42`: the first 24 train rows per class
  sorted by `document_id`. Rows carry IDs, filenames, class/stage, source corpus
  and `content_sha256` only; no document text is vendored.
- `replay.jsonl` — the scripted event trace (node starts/finishes, item results,
  checkpoints). Every agent choice, decision, score, latency and token count is
  fabricated for interface debugging. This is **not** a model run and its numbers
  must not be cited as results.
- `spec.lock.json` — replay identity: `engine.kind: replay`, the dataset sha256,
  the pinned corpus revision and the selection rule.
- `prompt.lock.json` — the simulated per-agent prompt stems (`sorter_local_v0`,
  `<class>_specialist_simplified`, …), locked so the run's prompt versions stay
  identifiable post hoc in the viewer; no prompt text or model output is claimed.

Human-review semantics scripted in the trace: one misclassified document reaches
`human_review` after `classification_arbiter`, is resolved there by the (simulated)
reviewer with the corrected label, and re-enters `extract` with the fresh label —
the graph's approved-review contract. Four other documents park OPEN at human
review (two judge-triggered, two extract-triggered, each with `review_causes`
naming the trigger), and three fail technically at extract. Parked documents
outcomes show as Held (review), never as Failed; the digest's `review_routed`
metric keeps every routed document count per trigger stage.

Source corpora and licenses are inherited from the dataset card; only identifiers
and metadata are copied here.

## Use

```bash
sandbox floor --replay --base <run-store>   # sample replayed INTO that base, next to its runs
sandbox floor                               # sample only when the base has no runs
sandbox floor --replay-run <recorded-run>   # a real Modal/OpenRouter/Ollama/… run, provider-agnostic
```

`--replay` resets just `runtime/runs/replay-mailroom-sample` inside the base and plays the
timeline in real time (~66 s): docs arrive staggered (a pilot-scale run) and stay in flight
for their recorded latencies (nodes run for ~0.1–1.8 s while other docs proceed), with a few
docs failing at extract, four parking open at human review and one classification review
resolved by the reviewer that re-enters extraction — so the run list, progress bar, class
rail, routing, node counts, RUNNING pills with growing elapsed timers, outcome buckets and
the Routed-to-human-review strip move like a live run while the base's historical runs stay
untouched and selectable in the same RUNS rail. The sample run persists in the base
afterwards (a finished recorded replay); an interrupted one reads like any killed run and
resets on the next `--replay`. No network, API key, GPU or local run data is needed.

For disposable UI checks, pass a scratch data directory as `--base`. Reset is
allowed only for an existing replay-owned run or an empty directory. Foreign
files, invalid locks and symlinked replay directories are refused; preserve
them and choose another base instead of deleting them to bypass the check.
The viewer binds `127.0.0.1:8769`; this fixture contains metadata and scripted
results, not document text for a model evaluation.

## Refresh the sample

See the [floor operator guide](../../../../docs/floor.md) for all CLI options,
live refresh, digest semantics and troubleshooting.

Re-draw the same rule from the pinned corpus (after `sandbox datasets pull`), then
update `dataset.jsonl`, its sha256 in `spec.lock.json` and the trace. The guard
test (`tests/test_floor_app.py::test_replay_fixture_is_a_pinned_sample_with_a_complete_trace`)
checks the class spread, row count, sha pin and that every traced document is in
the sample.
