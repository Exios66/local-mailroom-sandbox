# Scoring

Pinned engine: **[`llm-dojo-scoring` @ v0.11.0](https://github.com/Exios66/llm-dojo-scoring/releases/tag/v0.11.0)**
(tag `35f3584`). Formulas and T0 names are unchanged from v0.10.0. The 0.11
release adds canonical scoring docs and `llm_dojo_scoring.prompts`.

Sandbox wrapper: [`src/mailroom_sandbox/eval/scoring.py`](../../src/mailroom_sandbox/eval/scoring.py).

```python
from mailroom_sandbox.eval import scoring

print(scoring.score_classification(["contract", "correspondence"], ["contract", "correspondence"]))
```

Pin string in [`pyproject.toml`](../../pyproject.toml):

```
llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@v0.11.0
```

<details>
<summary>What gets scored</summary>

| Runner | Headline keys |
| --- | --- |
| Isolated classify | `exact_match` |
| Isolated extract | `overall_extraction_score` (typed fields) |
| `pipeline` | `class_correct`, `stage_correct`, extraction overall, `routing_accuracy` |
| `chained` | 0.25×sorter + 0.75×extract |
| `legalbench` | task exact match via `score_task("legalbench")` |

Never exact-match-on-extraction. Typed field scoring lives upstream in dojo
(`id` / `date` / `money` / names / lists).

Sinks: [`reports/scores/scores.jsonl`](../../reports/README.md) and the
sandbox [`experiment_log.jsonl`](../../reports/README.md) (not a sister-repo mirror).

</details>

<details>
<summary>Honesty / pins</summary>

- Mailroom **v0.5.0** (source via `sandbox fetch-deps`) still lists dojo v0.7.0, so mailroom is not a core pip extra that can coexist with v0.11.0 in one resolve. Use the vendor tree for source, `[pipeline]` for mailroom *main*.
- Mailroom *main* listed dojo `@v0.10.0` until its matching `@v0.11.0` pin lands. v0.11.0 is additive.
- Mock gold-against-gold scores 1.0 by construction. See [`notebooks/04_pipeline_and_scoring.ipynb`](../../notebooks/04_pipeline_and_scoring.ipynb).

</details>
