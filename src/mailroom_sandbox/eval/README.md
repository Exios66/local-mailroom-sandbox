<div align="center">

# 🧪 Evaluation Utilities

**Evaluation runners, scoring, matrix, and tracing for the sandbox.**

</div>

---

## Purpose

Drive evaluations against the sandbox pipeline — vendored mailroom agents
through the provider seam, with deterministic scoring and honest mock
labelling. Extraction rows are scoped to the live class schema before
the dojo suite runs (`extraction_scope`) so empty / other-class Hub GT
fields are not scored as misses.

## Surface

```python
from mailroom_sandbox.eval import runners, scoring, matrix, tracing

# per-agent isolated eval (sorter / contracts / specialists)
runners.run_isolated_eval(agent="sorter", model="mock/mock-...", ...)
# scoring helpers
scoring.accuracy(...)
scoring.exact_match(...)
scoring.compare_local_vs_api(...)
scoring.score_extraction_row(...)  # attaches parse_error / schema_valid
```

Pipeline runs report three cost-of-operation metrics beside the quality scores:
`routed_to_human_review*` (documents routed to a person, from `human_review.py`),
`incorrect_archives*` (incorrect archives, from `archive_correctness.py`) and `pain_points*` (the
client pain-point composites: classification and extraction penalty points, from
`pain_points.py`; see `docs/pain-point-composites.md`).

There is no top-level `run_evaluation` symbol — the entrypoints live in
`runners`. See `docs/evals.md` for the full eval-task surface and the
`AgentSpec` extension point.

## Related Files

- `../` — Package root
- `../../tests/` — Test suites
- `../../docs/evals.md` — Eval task reference
