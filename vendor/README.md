# vendor/

`sandbox fetch-deps` clones:

- `llm-mailroom` @ `v0.5.0`
- optionally `llm-entity-extraction` @ `v0.20.0` (`--entity`)

Checkouts are gitignored. The installed `mailroom` wheel does not ship
`scripts/` or `legalbench/`; the vendor tree supplies `PYTHONPATH` for
`sandbox pipeline watcher` / `sandbox pipeline api`.
