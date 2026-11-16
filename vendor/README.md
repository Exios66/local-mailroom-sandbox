# vendor/

Tracked, pinned snapshots of the family code the sandbox imports at runtime
(self-contained posture, DMR-057). **No `pip install ...@git...` is required —
the sandbox prepends these trees to `sys.path` on import.**

| Tree | Pin | Content |
| --- | --- | --- |
| `llm-mailroom/` | `abb1ccfaa352` (`v0.30.0` branch head after llm-mailroom #252: version 0.9.3 plus unified audit storage, the audit workbench, grounded-run scoring fixes, content-pinned frozen v1 prompts and the #241–#251 experiment fixes (opt-in `judge_rejudge_retry`); pre-release) | `src/` (minus tests) — `pipeline.*`, `graph.*`, `agents.*`, `llm.*`, `legalbench.*`, `observability.*`, `langchain_agents.*`, `scripts.*` |
| `llm-dojo-scoring/` | `13adc8ec722f` (`v0.30.0` branch head after llm-dojo-scoring #163: version 0.30.0, production slim-down plus the #159–#162 scoring fixes; pre-release) | `src/llm_dojo_scoring/` — scoring engine (`serving`, `experiment`, `extraction_metrics`, incl. the per-subclass `corporate_record_schema`) |

Provenance + refresh details live in each tree's `VENDOR.md`. `sandbox fetch-deps`
re-snapshots both trees from their pinned refs (network, optional). The
installed `mailroom` wheel does not ship `scripts/` or `legalbench/`; the
vendored tree supplies `PYTHONPATH` for `sandbox pipeline watcher` /
`sandbox pipeline api`.