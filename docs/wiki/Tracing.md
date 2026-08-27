# Tracing

Canonical sink: **Langfuse 3** (Python SDK v4 data model) on
`http://localhost:3000`. Same contract llm-mailroom writes and The-Mailroom
reads. How-to: [`docs/tracing.md`](../tracing.md). Code:
[`eval/tracing.py`](../../src/mailroom_sandbox/eval/tracing.py).

```python
from mailroom_sandbox.eval import tracing

print(tracing.PIPELINE_TRACE)  # document-pipeline
print(tracing.default_tags("source-fixtures"))
print(tracing.public_ground_truth({"expected_doc_class": "contract", "expected_fields": {"secret": True}}))
# -> {'expected_doc_class': 'contract'}   # expected_fields stripped
```

<details>
<summary>Family data model</summary>

| Field | Value |
| --- | --- |
| root name | `document-pipeline` |
| root type | `chain` |
| children | verb-first names in `NODE_OBSERVATION_TYPES` |
| `session_id` | `sandbox-<task>-<utc>` for evals |
| tags | `mailroom`, `mock`/`pilot`, `sandbox`, profile |
| public GT | `expected_hf_class`, `expected_doc_class`, `expected_subclass`, `expected` only |

Isolated evals still open the root chain and nest the one relevant observation.

Score names follow mailroom `SCORE_CONFIGS` / dojo aliases
(`extraction_overall_verified_precision` → `extraction_verified_precision`).

Notebook: [`notebooks/05_tracing_contract.ipynb`](../../notebooks/05_tracing_contract.ipynb).

</details>

<details>
<summary>The-Mailroom</summary>

```bash
sandbox fetch-deps --visualizer
# LANGFUSE_HOST=http://localhost:3000
# MAILROOM_TRACE_NAMES=document-pipeline
# MAILROOM_TRACE_TAGS=mailroom
# MAILROOM_TRACE_ENVIRONMENTS=mock,pilot
```

Phoenix is an optional sidecar (`sandbox up --compose-profile phoenix`).
The-Mailroom **cannot** plot Phoenix spans.

Headless keys in [`config/.env.example`](../../config/.env.example):
`pk-lf-sandbox` / `sk-lf-sandbox`.

</details>
