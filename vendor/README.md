# vendor/

Tracked, pinned snapshots of the family code the sandbox imports at runtime
(self-contained posture, DMR-057). **No `pip install ...@git...` is required —
the sandbox prepends these trees to `sys.path` on import.**

| Tree | Pin | Content |
| --- | --- | --- |
| `llm-mailroom/` | `8cebcd865217` (`main` after llm-mailroom #287, the v0.30.0 release line: version 0.9.3, all of `main` at `10c1d93` plus the #260 `choices: null` fix, decision-reviewer error recording, correspondence typed by content, #280 insurance `claim_type` as the product line the Dojo pin at `025400f`, #283 CMS `cms_source_table` and `supporting_documents`, the opt-in interim GT overlay (#284), routing as data (#286) and off-by-default decision points (#289, #291); pre-release) | `src/` (minus tests) — `pipeline.*`, `graph.*`, `agents.*`, `llm.*`, `legalbench.*`, `observability.*`, `langchain_agents.*`, `scripts.*` |
| `llm-dojo-scoring/` | `025400f3d703` (`v0.30.0` branch head after llm-dojo-scoring #174, untagged: version 0.30.1, production slim-down, the #159–#163 scoring fixes, the correspondence v8 prompt candidate, the #168 decision-lane fix and #173 recall-only CUAD dates) | `src/llm_dojo_scoring/` — scoring engine (`serving`, `experiment`, `extraction_metrics`, incl. the per-subclass `corporate_record_schema`) |

Provenance + refresh details live in each tree's `VENDOR.md`. `sandbox fetch-deps`
re-snapshots both trees from their pinned refs (network, optional). The
installed `mailroom` wheel does not ship `scripts/` or `legalbench/`; the
vendored tree supplies `PYTHONPATH` for `sandbox pipeline watcher` /
`sandbox pipeline api`.