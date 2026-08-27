# FAQ

<details>
<summary>Why isn't mailroom a core pip dependency?</summary>

Scoring is pinned to **dojo v0.11.0**. The llm-mailroom **v0.5.0 tag** still
depends on dojo v0.7.0. Pip cannot satisfy both. `sandbox fetch-deps` clones
the v0.5.0 **source tree**. `pip install -e ".[pipeline]"` installs current
mailroom *main* (dojo `@v0.10.0` until mailroom lands `@v0.11.0`; v0.11.0 is
additive).

See [`pyproject.toml`](../../pyproject.toml) and [`AGENTS.md`](../../AGENTS.md).

</details>

<details>
<summary>Why do mock evals always score 1.0?</summary>

Mock predictors copy gold labels/fields. That proves runners, sinks, and
tracing — not a local model. Use `sandbox eval sorter --local` after
`sandbox pull-models`.

</details>

<details>
<summary>Why did Ollama try to pull `qwen/qwen3.7-flash`?</summary>

You set `DEFAULT_PROVIDER` without the overlay rewrite. Run
`sandbox cutover` and confirm every agent shows a local tag (`qwen3:8b`, not
a slash-id). Notebook: [`01_activate_overlay.ipynb`](../../notebooks/01_activate_overlay.ipynb).

</details>

<details>
<summary>Can The-Mailroom see Phoenix traces?</summary>

No. Phoenix is an optional sidecar. The-Mailroom is Langfuse-only. Use
`sandbox up` (langfuse profile) and tags `mailroom` + `document-pipeline`.

</details>

<details>
<summary>Where is the kanban board?</summary>

There is no second board here. Cross-family work stays on
llm-entity-extraction's MESSAGE_BOARD. Family map:
[`docs/sister-repos.md`](../sister-repos.md).

</details>

<details>
<summary>ClickHouse / GitGuardian CI failed on compose?</summary>

Healthchecks must not pass `--password` or `--requirepass`. Redis in the
Langfuse stack is unpassworded for that detector.

</details>
