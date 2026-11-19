# Re-scoring a finished run (`sandbox rescore`)

A run stores every answer it was given (`items.jsonl`, the raw `pred` of each document). When the
truth changes after the run, the answers are still valid and only the scores are stale. A dataset
revision (v9.1 to v9.3), a label-overlay update and a scoring hotfix all change the truth.
`sandbox rescore` scores the stored answers again against the new truth. It makes no model call,
so moving the calibration of a decision model to new labels does not cost a second run.

```bash
sandbox rescore <run> --revision v9.3 --dry-run
```

`<run>` is a run id under `data/runtime/runs`, a run directory, or a committed report bundle
(`reports/campaigns/<campaign>/<study>/<run>/<iteration>/`).

## Truth sources

| Option | New truth |
| --- | --- |
| none | The run's own revision and overlays. Use this to measure scorer drift alone. |
| `--revision v9.3` (tag or commit) | The run's documents, read from that revision's full corpus. The draw is not repeated, so a revision that would draw differently still scores the same documents. |
| `--dataset-file truth.jsonl` | A local JSONL of truth rows, such as hand-corrected labels. |
| `--overlays lock\|none\|all` | Label overlays: those the run used (default, at their current content), none, or both interim and near-gold. |

`--ids-file` or `--set dev-look1` (with `--split-dir`) re-scores only those documents.

## What it writes

The source run is never modified. The result is a derived run directory, by default
`data/runtime/runs/<run_id>.rescore-<label>`, in the runtime layout. `compare_sorter_arms` and
the gold audit read that layout.

- `spec.lock.json`: the source lock. Its `dataset` block describes the new truth. It also gets
  `lock_kind: rescore.lock`, the new `run_id`, and a `rescore` block that names the source run
  and keeps the source `dataset` block.
- `dataset.jsonl`: the new truth rows, in item order.
- `items.jsonl`: each answered item with its new `score`. The first score it ever had is kept in
  `score_original`, including when a rescore is itself re-scored. Errored and unparseable items
  have no answer to score and are copied unchanged.
- `rescore.json`: the provenance and the digest the command prints.
- `events.jsonl`, `checkpoint.json` and `prompt.lock.json`, copied when present.

## Reading the digest

For each headline key (`match`, `subclass_match`, `overall_extraction_score`, ...) the digest
shows the mean before and the mean after, each over the items that have the key. It also shows
the mean paired delta over items scored both times, and the count of items whose score changed.
The digest also reports:

- score keys gained or lost (a hotfix can add a key, such as `subclass_match` from SHF-013);
- truth changes: class and subclass label moves, and documents whose expected fields changed.
  For a report bundle, which has no `dataset.jsonl`, the source truth is rebuilt from the lock;
- a note when the scoring hotfixes in effect differ from the run's lock. Part of any delta then
  comes from the scorer, not the truth. To separate the two, re-score once with no options
  (scorer drift only), then with `--revision` (scorer and truth).

## Refusals

A rescore stops and writes nothing if any of these hold:

- a document is missing from the new truth (`--allow-missing` leaves it out and lists it, so no
  stale score sits beside new ones);
- the run's checkpoint says `running`;
- `--out` already exists (`--force` replaces it), or `--out` is the source run;
- the task has no per-document scorer.

Supported tasks are `pipeline`, `specialist`, `isolated` (the sorter) and every registered agent
task. A rescore uses the scorer code of the current checkout.
