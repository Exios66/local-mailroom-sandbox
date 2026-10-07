# HUB-230 — Insurance schema validity (SPEND-GATED)

**Hub issue:** [mailroom-issues#230](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/230)  
**Proposed busy-window cap:** `$0.80`  
**Modal app:** `sandbox-vllm-hub230`  
**Priority:** P1 — score ~0.688 but schema validity ~22% on Modal.

> **SPEND-GATED — do not run until Jack go.**

## Goal

Raise schema validity to **≥90%** without `overall_extraction_score` below **0.65** on n=50.

## Baseline

Reproduce `sand032-s3-insurance50` via `hub230-insurance50-baseline.yaml` (same pin, isolated app name).

## Guided decoding / constrained JSON — harness gap

The sandbox **`sandbox.run/v1` RunSpec** and `deploy_env` path do **not** expose a first-class flag to enable vLLM guided JSON / structured-output at the engine layer for specialist isolated evals. LangChain agents use `with_structured_output` client-side (`json_schema` method), which is already the default path — the 22% schema rate is a **model+prompt** problem, not a missing YAML knob.

`hub230-insurance50-guided-json.yaml` is a **documented stub**:

- Do **not** add invented `engine.vllm.*` keys (they are ignored or fail validation).
- A future harness change might add e.g. `job.structured_output: guided` or per-agent `response_format` — track on hub #230 before spend.

Until then, experiments are: baseline · prompt variants · `SANDBOX_AGENT_KNOBS` (max_tokens) · thinking-off verify (already off in L5).

## Cross-links

| Card | Note |
| --- | --- |
| [mailroom-issues#224](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/224) | Metric protocol for reporting schema % |
| [mailroom-issues#205](https://github.com/LLM-Mailroom-Services/mailroom-issues/issues/205) | COST verdict if API remains preferred |

## Run cells

| Config | Purpose |
| --- | --- |
| `hub230-insurance50-baseline.yaml` | Clone SAND-032 insurance n=50 |
| `hub230-insurance50-guided-json.yaml` | Stub — enable when harness supports engine-level guided decode |
| `hub230-insurance50-shorter-decode.yaml` | Lower max_tokens via `SANDBOX_AGENT_KNOBS` (schema vs completeness tradeoff) |

### Shorter decode knobs

```bash
export SANDBOX_AGENT_KNOBS='{"insurance_claims_specialist":{"max_tokens":2048,"max_input_chars":28000}}'
```

## Operator outline

1. Baseline schema % from `sand032-s3-insurance50`.
2. If harness lands guided JSON, A/B using `hub230-insurance50-guided-json.yaml`.
3. If schema ↑ but score ↓ >0.03 vs baseline, stop and report.
4. Document API vs Modal preference in COST thread.
