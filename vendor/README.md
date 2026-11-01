# vendor/

Tracked, pinned snapshots of the family code the sandbox imports at runtime
(self-contained posture, DMR-057). **No `pip install ...@git...` is required —
the sandbox prepends these trees to `sys.path` on import.**

| Tree | Pin | Content |
| --- | --- | --- |
| `llm-mailroom/` | `175e6711077f` (reviewed `main` commit) | `src/` (minus tests) — `pipeline.*`, `graph.*`, `agents.*`, `llm.*`, `legalbench.*`, `observability.*`, `langchain_agents.*`, `scripts.*` |
| `llm-dojo-scoring/` | `e35504db12f0` (0.25.0 release merge commit: sorter subclass guide, zero-token fix) | `src/llm_dojo_scoring/` — scoring engine (`serving`, `experiment`, `extraction_metrics`, incl. the per-subclass `corporate_record_schema`) |

Provenance + refresh details live in each tree's `VENDOR.md`. `sandbox fetch-deps`
re-snapshots both trees from their pinned refs (network, optional). The
installed `mailroom` wheel does not ship `scripts/` or `legalbench/`; the
vendored tree supplies `PYTHONPATH` for `sandbox pipeline watcher` /
`sandbox pipeline api`.