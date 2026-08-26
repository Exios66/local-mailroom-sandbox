# Evals

All runners are `--dry-run` capable, append one JSONL record per completed
experiment, and score with `llm-dojo-scoring` (never exact-match-on-extraction).

```bash
sandbox eval sorter --mock
sandbox eval extract --mock --sample 4
sandbox eval chained --mock
sandbox eval pipeline --mock
sandbox eval legalbench --mock
sandbox matrix --providers ollama --models qwen3:8b,llama3.1:8b \
  --prompts mailroom-default,sorter_local_v0 --sample 10 --seed 42 --dry-run
```

`--local` uses the active profile's OpenAI-compatible server. `--mock` uses a
deterministic fake client (expected labels from `data/fixtures/manifest.csv`).

## Experiment log

`reports/experiment_log.jsonl` is **sandbox-local**. It is not a mirror of
llm-entity-extraction. Each record carries profile, provider, model, prompt
version, dataset fingerprint, scores + bootstrap CI when available, tracing
backend, tags, and a git snapshot.

Markdown is regenerated next to the JSONL on every append.

## Fixtures

Offline catalog: `data/fixtures/` (see `ATTRIBUTION.md`). Tiny HF slice:
`data/fixtures/hf/docclass_mini.jsonl`. LegalBench Yes/No:
`data/fixtures/legalbench/contract_qa.jsonl`.

`sandbox datasets pull` streams a Hub head into `data/cache/` when network is
allowed.

## Prompt variants

`config/prompts/sorter_local_v0.txt` is a shorter, JSON-strict sorter prompt
for 7B/8B local models. Pass `--prompt sorter_local_v0`.
