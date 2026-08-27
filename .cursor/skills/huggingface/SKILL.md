---
name: huggingface
description: Hugging Face Hub usage for local-mailroom-sandbox — fixture schema, sandbox datasets pull, HF cache, and Modal/vLLM weight downloads. Use for Hub datasets, HF_TOKEN, docclass-merged slices, or model pulls; prefer offline data/fixtures and sandbox datasets prepare when network-free work is enough. For general Hub CLI depth, also follow the hf-cli plugin skill.
---

# Hugging Face (sandbox data + weights)

**When:** Hub dataset pulls, model downloads for vLLM/Modal/Ollama-from-Hub, `HF_TOKEN`, or docclass schema work.  
**Prefer offline fixtures** (`data/fixtures/`, `sandbox datasets prepare`) for default tests and notebooks 01–03. Never require Hub in pytest.

## Offline first

| Asset | Path | Network? |
| --- | --- | --- |
| Catalog + gold | `data/fixtures/` (+ `ATTRIBUTION.md`) | No |
| Synthetic HF mini slice | `data/fixtures/hf/docclass_mini.jsonl` | No |
| Prepared JSONL | `data/runtime/prepared/` via `sandbox datasets prepare` | No |
| Hub head cache | `data/cache/` via `sandbox datasets pull` | **Yes** |

```bash
sandbox datasets prepare                                    # offline cleaners
sandbox datasets pull --dataset Lucius-Morningstar/docclass-merged --max-rows 50
```

Default Hub id in code: `Lucius-Morningstar/docclass-merged` (`mailroom_sandbox.datasets.HF_DATASET`).

## Auth + cache

```bash
# optional
export HF_TOKEN=hf_...
# compose vLLM / Modal read HF_TOKEN; Modal volume sandbox-hf-cache
```

Compose `vllm` mounts named volume `hf_cache`. Modal uses `HF_HUB_ENABLE_HF_TRANSFER=1` on the vLLM image.

## When to use which HF surface

| Task | Tool |
| --- | --- |
| Sandbox evals / pilots | Offline fixtures + prepared JSONL |
| Stream a tiny Hub slice | `sandbox datasets pull` / `pull_hf_dataset` |
| Choose a local GGUF / serve recipe | Prefer [ollama](../ollama/SKILL.md) or llama.cpp profile; use Hub only for the weight source |
| Deploy weights on Modal | [modal](../modal/SKILL.md) + `HF_TOKEN` if gated |
| Full Hub CLI (upload, buckets, papers, …) | Cursor **hf-cli** / other Hugging Face plugin skills — this skill stays sandbox-scoped |

## Boundaries

- Do not vendor multi-MB CUAD PDFs; pull from mailroom `docs/examples/samples/` after `sandbox fetch-deps` (see fixture attribution).  
- Synthetic `hf/docclass_mini.jsonl` matches Hub schema but is **not** Hub content.  
- Default CI/pytest: no Hub calls.

## Related

- Router: [sandbox-tool-router](../sandbox-tool-router/SKILL.md)  
- Evals: `docs/evals.md`  
- Attribution: `data/fixtures/ATTRIBUTION.md`
