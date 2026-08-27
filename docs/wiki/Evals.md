# Evals

Isolated evals cover every **live** agent/node. Connected `pipeline` scores
class, stage, extraction, and routing together. How-to:
[`docs/evals.md`](../evals.md).

```bash
sandbox agents list
sandbox eval sorter --mock
sandbox eval judge --mock
sandbox eval pipeline --mock
sandbox eval chained --mock
sandbox eval legalbench --mock
```

Python:

```python
from mailroom_sandbox.eval.runners import run_isolated_eval, run_pipeline_eval

print(run_isolated_eval("sorter", mock=True, sample=4)["scores"])
print(run_pipeline_eval(mock=True, sample=3, connected=True)["scores"])
```

Notebooks: [`03_isolated_agent_evals.ipynb`](../../notebooks/03_isolated_agent_evals.ipynb),
[`04_pipeline_and_scoring.ipynb`](../../notebooks/04_pipeline_and_scoring.ipynb).

<details>
<summary>Isolated observation map</summary>

| Task | Observation | Type |
| --- | --- | --- |
| `intake` | `normalize-intake` | span (dojo deterministic) |
| `pdf_transcriber` / `image_extractor` | `transcribe-pdf` / `extract-image-text` | retriever |
| `sorter` / `sorter_reviewer` | `classify-document` | agent |
| five specialists | `extract-fields` | agent |
| `judge` | `judge-verify` | evaluator |
| `arbiter` / `boss` / `reporter` | matching verb-first names | agent |
| `human_review` / `catalog` / `archive` | procedural | span |

Registry: [`eval/agents.py` `SPECS`](../../src/mailroom_sandbox/eval/agents.py).
Retired specialists have **no** runners.

</details>

<details>
<summary>Mock vs local</summary>

- **`--mock`** (default): gold copy / [`mock_llm.fake_client`](../../src/mailroom_sandbox/mock_llm.py). `exact_match == 1.0` is harness proof.
- **`--local`**: active profile's OpenAI-compatible server. Needs `sandbox fetch-deps` for live agent classes. If `live_predict` raises, the runner falls back to mock and sets `offline_fallback`.
- **`--dry-run`**: plan only (n, fingerprint, observation) — no writes.

`ambiguous_01` gets mock confidence `0.40` so routing has a REVIEW case.

</details>

<details>
<summary>Fixtures</summary>

Catalog: [`data/fixtures/`](../../data/fixtures) +
[`ATTRIBUTION.md`](../../data/fixtures/ATTRIBUTION.md).
Loader: [`datasets.py`](../../src/mailroom_sandbox/datasets.py).

Notebook: [`notebooks/02_fixtures_catalog.ipynb`](../../notebooks/02_fixtures_catalog.ipynb).

`sandbox datasets pull` is the **network** Hub path into `data/cache/`.

</details>
