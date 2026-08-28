# Evals

Isolated evals cover every live pipeline agent / node. Connected `pipeline`
runs the vendored 13-node graph (when `sandbox fetch-deps` is present) and
scores classification, stage, extraction, and routing together. All runners
are `--dry-run` capable, append one JSONL record per completed experiment,
and score with `llm-dojo-scoring` (never exact-match-on-extraction).

```bash
sandbox agents list
sandbox agents show judge
sandbox cutover --agent-model judge=qwen3:14b

sandbox eval sorter --mock
sandbox eval sorter_reviewer --mock
sandbox eval contracts_specialist --mock
sandbox eval judge --mock
sandbox eval arbiter --mock
sandbox eval pipeline --mock          # connected: class + stage + extract + routing
sandbox eval chained --mock           # sorter → extract only
sandbox eval legalbench --mock
sandbox eval local_vs_api --mock  # fixture timings; no OPENROUTER_API_KEY
sandbox eval local_vs_api --from-log  # pair experiment_log local vs API-key rows
sandbox matrix --task judge --providers ollama --models qwen3:8b \
  --prompts mailroom-default --sample 2 --mock --dry-run
sandbox matrix --task sorter --providers ollama,openrouter \
  --models qwen3:8b --prompts mailroom-default --mock
```

`--local` uses the active profile's OpenAI-compatible server (`sandbox fetch-deps`
required for live agent classes). `--mock` uses deterministic fixtures / the fake
client. `local_vs_api` is importable dojo serving comparison (`get_suite("local_vs_api")`):
TTFT stays `None` unless recorded; GPU/KV/VRAM are stripped on API-key records;
local Ollama cost stays `None` without a price table. Sorter headlines stay
`accuracy` + `f1_macro`.

## Isolated vs connected

| Task | What runs | Observation |
| --- | --- | --- |
| `intake` | dojo `deterministic_normalize` | `normalize-intake` span |
| `pdf_transcriber` / `image_extractor` | transcriber / vision agent | retriever |
| `sorter` / `sorter_reviewer` | classifier | `classify-document` agent |
| five live specialists | `.extract()` | `extract-fields` agent |
| `judge` | completeness judge | `judge-verify` evaluator |
| `arbiter` / `boss` / `reporter` | named agents | matching agent spans |
| `human_review` / `catalog` / `archive` | procedural gold | matching spans |
| `pipeline` | full graph (or offline mock fallback) | `document-pipeline` chain |
| `chained` | sorter + extract only | (composite) |
| `local_vs_api` | dojo serving suite (fixtures or experiment log) | (serving; no Langfuse score names on sorter) |

Retired specialists (`court_opinions_specialist`, `due_diligence_specialist`)
are listed in `config/components.yaml` and skipped.

## Experiment log

`reports/experiment_log.jsonl` is **sandbox-local**. It is not a mirror of
llm-entity-extraction. Each record carries profile, provider, `serving_kind`
(`local` | `api`), model, prompt version, dataset fingerprint, scores +
bootstrap CI when available, tracing backend, tags, session id, and a git
snapshot. Mixed local + API-key matrix runs attach a `local_vs_api` block
from the same importable suite.

Markdown is regenerated next to the JSONL on every append.

## Fixtures

Offline catalog: `data/fixtures/` (see `ATTRIBUTION.md`). Tiny HF slice:
`data/fixtures/hf/docclass_mini.jsonl`. LegalBench Yes/No:
`data/fixtures/legalbench/contract_qa.jsonl`. Per-agent gold:
`data/fixtures/agents/*.jsonl`. Tiny PDF/PNG: `data/fixtures/intake/`.
Synthetic serving pair: `data/fixtures/serving/local_vs_api.json`.

`sandbox datasets pull` streams a Hub head into `data/cache/` when network is
allowed. `sandbox datasets prepare` (and notebooks `01`–`03`) clean the offline
catalog into `data/runtime/prepared/` with no network — see
[`docs/docker-offline.md`](docker-offline.md).

## Prompt variants

`config/prompts/*_local_v0.txt` are shorter, JSON-strict templates for 7B/8B
local models. Pass `--prompt sorter_local_v0` (or `sorter_reviewer_local_v0`,
`judge_local_v0`). Per-agent prompt stems also live under
`config/components.yaml` `prompts:`.

## Component gates

`config/components.yaml` enables/disables isolated evals and overlays
confidence routing onto `data/runtime/taxonomy.yaml`. It does not fork the
LangGraph topology.
