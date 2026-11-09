# Floor replay sample

A small, pinned sample of the public core corpus plus a **scripted** pipeline trace,
so `sandbox floor` can be viewed and debugged on a machine with no run store.

## What is here

`runtime/runs/replay-mailroom-sample/`

- `dataset.jsonl` — 20 docs, 4 per live class, drawn from
  `Lucius-Morningstar/mailroom-dataset` config `ground_truth` at revision
  `bc9eab280044befb51e19dda3071d290a8677f42`: the first 4 train rows per class
  sorted by `document_id`. Rows carry IDs, filenames, class/stage, source corpus
  and `content_sha256` only; no document text is vendored.
- `replay.jsonl` — the scripted event trace (node starts/finishes, item results,
  checkpoints). Every agent choice, decision, score, latency and token count is
  fabricated for interface debugging. This is **not** a model run and its numbers
  must not be cited as results.
- `spec.lock.json` — replay identity: `engine.kind: replay`, the dataset sha256,
  the pinned corpus revision and the selection rule.

Source corpora and licenses are inherited from the dataset card; only identifiers
and metadata are copied here.

## Use

```bash
sandbox floor --replay --base <run-store>   # sample replayed INTO that base, next to its runs
sandbox floor                               # sample only when the base has no runs
```

`--replay` resets just `runtime/runs/replay-mailroom-sample` inside the base and appends
the trace one document per tick (0.8 s), so the run list, progress bar, class rail, routing,
node counts and outcome buckets move while the base's historical runs stay untouched and
selectable in the same RUNS rail. The sample run persists in the base afterwards (a finished
recorded replay); an interrupted one reads like any killed run and resets on the next
`--replay`. No network, API key, GPU or local run data is needed.

## Refresh the sample

Re-draw the same rule from the pinned corpus (after `sandbox datasets pull`), then
update `dataset.jsonl`, its sha256 in `spec.lock.json` and the trace. The guard
test (`tests/test_floor_app.py::test_replay_fixture_is_a_pinned_sample_with_a_complete_trace`)
checks the class spread, row count, sha pin and that every traced document is in
the sample.
