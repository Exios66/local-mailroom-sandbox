# vendor/

Tracked, pinned snapshots of the family code the sandbox imports at runtime
(self-contained posture, DMR-057). **No `pip install ...@git...` is required —
the sandbox prepends these trees to `sys.path` on import.**

| Tree | Pin | Content |
| --- | --- | --- |
| `llm-mailroom/` | `63f6841ec6a5` (`v0.30.0` branch head after llm-mailroom #271: version 0.9.3, all of `main` at `10c1d93` plus the #260 `choices: null` fix, decision-reviewer error recording and correspondence typed by content; pre-release) | `src/` (minus tests) — `pipeline.*`, `graph.*`, `agents.*`, `llm.*`, `legalbench.*`, `observability.*`, `langchain_agents.*`, `scripts.*` |
| `llm-dojo-scoring/` | `116da0b0f510` (tag `v0.30.1`, the `v0.30.0` branch head after llm-dojo-scoring #169: version 0.30.0, production slim-down, the #159–#163 scoring fixes, the correspondence v8 prompt candidate and the #168 decision-lane fix) | `src/llm_dojo_scoring/` — scoring engine (`serving`, `experiment`, `extraction_metrics`, incl. the per-subclass `corporate_record_schema`) |

Provenance + refresh details live in each tree's `VENDOR.md`. `sandbox fetch-deps`
re-snapshots both trees from their pinned refs (network, optional). The
installed `mailroom` wheel does not ship `scripts/` or `legalbench/`; the
vendored tree supplies `PYTHONPATH` for `sandbox pipeline watcher` /
`sandbox pipeline api`.