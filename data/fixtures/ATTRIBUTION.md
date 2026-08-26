# Fixture attribution

Text fixtures in this directory are **copied from**
[`Exios66/llm-mailroom`](https://github.com/Exios66/llm-mailroom) `v0.5.0`
(`src/tests/fixtures/` and `docs/examples/sources/`). They are original
synthetic documents written for that repo unless noted.

The full 22-sample PDF pilot (CUAD / Atticus, CC BY 4.0) is **not** vendored
here (binary, multi-MB). Pull it from the mailroom checkout:

```bash
sandbox fetch-deps
# then copy vendor/llm-mailroom/docs/examples/samples/
```

See mailroom `docs/examples/samples/ATTRIBUTION.md` for CUAD license terms.

Tiny HF JSONL under `hf/` is a **synthetic** one-doc-per-class slice matching
the `Lucius-Morningstar/docclass-merged` schema (not Hub content). Use
`sandbox datasets pull` for real Hub rows.

LegalBench fixtures under `legalbench/` are short synthetic Yes/No items for
offline harness tests, not the Stanford LegalBench corpus.
