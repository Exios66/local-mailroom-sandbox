# Archived campaign scripts

Scripts from finished campaigns, kept as the record of how those runs were
launched. Nothing in the repository calls them, and they are not maintained:
usage lines inside them still name their old `scripts/sand032/` and
`scripts/sand42/` paths, and the paths they reference may have moved.

Most of them spend money (`modal deploy`, `sandbox run start`). Do not run one
to reproduce a result; start from the current runbook (`sandbox runbook list`)
and the run configs under `config/runs/`.

| Folder | Campaign | Scripts |
| --- | --- | --- |
| `sand032/` | SAND-032 serving ladder | `flow2.sh` … `flow5.sh`: stages 6–10 after `scripts/sand032/flow.sh` |
| `sand42/` | SAND-042 concurrency × fleet grid | the `rerun-*`, `contracts-only-rerun` and `smoke-metrics-gate` re-runs, and the `campaign-attention`, `campaign-pager` and `campaign-sitter` babysitting scripts (SAND-054) |
