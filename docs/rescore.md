# Re-scoring a finished run (`sandbox rescore`)

A run of a per-document task stores every answer it was given (`items.jsonl`, the raw `pred` of
each document; see the supported tasks under Refusals). When the truth changes after the run, the answers are still valid and only the scores are stale. A dataset
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
| none | The run's own revision, with the overlays it used at their current content. This measures scorer drift alone only while those overlays are unchanged since the run. A run that read a local dataset file has no Hub revision to fall back on: give `--dataset-file`, or `--revision` for the Hub. |
| `--revision v9.3` (tag or commit) | The run's documents, read from that revision's full corpus. The draw is not repeated, so a revision that would draw differently still scores the same documents. |
| `--dataset-file truth.jsonl` | A local JSONL of truth rows, such as hand-corrected labels. |
| `--overlays lock\|none\|all` | Label overlays: those the run used (default, at their current content), none, or both interim and near-gold. |

`--ids-file` or `--set dev-look1` (with `--split-dir`) re-scores only those documents.

Interim labels are read as a validated snapshot: the manifest fingerprint, applied records and
review checks use the same bytes. A rebuild that leaves a shard inconsistent with its manifest
is refused before any derived run is written. Subset preparation, Parquet overlays and the
near-gold precedence cache use the same snapshot contract.

## What it writes

The source run is never modified. The result is a derived run directory, by default
`data/runtime/runs/<run_id>.rescore-<label>`, in the runtime layout. `compare_sorter_arms` and
the gold audit read that layout.

- `spec.lock.json`: the source lock. Its `dataset` block describes the new truth. It also gets
  `lock_kind: rescore.lock`, the new `run_id`, and a `rescore` block that names the source run
  and keeps the source `dataset` block and the overlays its truth was built with
  (`overlays_effective`, which a rescore of the derived run reads). When the truth is on another revision, the source's
  split file (`exclude_ids_file`) is left out of `dataset`. Splits assign sets per revision: a
  runbook-v1 dev document can be held out in runbook-v2. Readers then resolve the split of the
  new revision, and its held-out checks apply. The source's split stays in `rescore.source_dataset`.
- `dataset.jsonl`: the new truth rows, in item order.
- `items.jsonl`: each answered item with its new `score`. The first score it ever had is kept in
  `score_original`, including when a rescore is itself re-scored. Errored and unparseable items
  have no answer to score and are copied unchanged.
- `scores.json`: run-level means of every numeric per-item score, overall and by class. These are
  plain means. A task runner's own run summary can hold other statistics (macro-F1, intervals),
  which a rescore does not recompute.
- `rescore.json`: the provenance, the digest the command prints, and the same run-level scores.
- `events.jsonl` and `prompt.lock.json`, copied when present. `checkpoint.json` uses the
  derived lock's run, spec and generation identity, retaining its original content under
  `source_checkpoint`. Its terminal state is preserved.

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
  (scorer drift only, provided the run's overlays are unchanged; else add `--overlays none` on
  both), then with `--revision` (scorer and truth).

## Refusals

A rescore stops and writes nothing if any of these hold:

- a document is missing from the new truth (`--allow-missing` leaves it out and lists it, so no
  stale score sits beside new ones);
- the run's checkpoint says `running`;
- `--out` already exists (`--force` replaces it), or `--out` is the source run, contains it or lies
  inside it;
- the run read a local dataset file and neither `--dataset-file` nor `--revision` is given;
- the new truth source has duplicate normalized document IDs, even if only one is requested;
- the task has no per-document scorer.

Supported tasks are `pipeline`, `specialist`, `isolated` (the sorter) and every registered agent
task. `extract`, `chained`, `local_vs_api` and `sorter_vs_modernbert` keep only run-level scores
and store no per-document answers, so they are refused. A rescore uses the scorer code of the
current checkout.

## Using a derived run

- Gold audit (`scripts/build_gold_audit_sheet.py`): reads a derived run like any other. A v9.3
  rescore of a v9.1 run is audited against runbook-v2 and its field registry.
- `compare_sorter_arms`: pairs runs on the same revision and truth. An original run and its
  rescore pair only when the labels did not move, which makes a scorer-drift check. To compare
  two arms on new labels, re-score both to the same revision and pair the two derived runs. An
  original paired with a rescore on another revision is refused (`dataset revisions differ`).
