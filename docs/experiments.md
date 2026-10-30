# Design and launch an experiment

The `sandbox experiment` commands compose the existing locked run lifecycle and
vendored mailroom pipeline. They select a design, prepare paired document draws,
review every configuration, require initials for spend, smoke a small locked subset,
launch sequential cells, stop their managed apps, and compile outcome reports.
Creating or reviewing an experiment never calls Hugging Face, an LLM, or Modal.
Preflight may download the pinned Hub data; it does not deploy or probe an LLM.

## Select the design and settings

```bash
sandbox experiment designs
sandbox modal-matrix list
sandbox agents list
sandbox experiment create --help
```

`single` creates one cell. `sand42` creates the four replica/concurrency cells
`1×8`, `1×16`, `2×8`, and `2×16`. Each class uses the same pinned revision, seed,
and exact prepared dataset bytes across cells; preflight refuses different draws.
The default task runs all five specialists, with 50 documents per class and
proportional subclass quotas from the SAND42 templates. Sample sizes smaller than
the number of subclasses cover only the largest strata; review `strata_actual`
before signing. Repeated `--doc-class` and `--subclass` narrow the corpus.

```bash
sandbox experiment create sand42-next \
  --design sand42 --samples 50 --seed 42 \
  --model Qwen/Qwen3-8B-AWQ --gpu L4 \
  --set engine.vllm.max_num_seqs=16 \
  --set engine.vllm.gpu_memory_utilization=0.90 \
  --max-tokens 8192 --temperature 0.1 \
  --trace-sink langfuse --cost-cap-usd 1.00 --max-wall-seconds 2400
```

By default this writes `config/experiments/sand42-next/experiment.yaml` and its
run YAMLs. `--output DIR` chooses another new directory. Existing directories
are never overwritten. `--set PATH=YAML_VALUE` changes existing nested fields,
including vLLM options, prompts, job settings, and per-agent generation knobs;
unknown paths fail. `--design single` also accepts `--replicas` and `--concurrency`.
`--gpu H100` selects another GPU class; `--gpu A100-80GB:2` requests tensor parallel
GPUs within each container, while `--replicas 2` means independent containers.

Hub selectors are `--dataset`, `--dataset-config`, `--split`, `--revision` (a full
commit SHA), `--samples`, `--seed`, `--doc-class`, and `--subclass`. The default is
the family's frozen dataset SHA and all splits. `--local-dataset FILE.jsonl` uses
a local fixture instead. New studies have distinct run IDs and app names.

## Full pipeline and per-agent models

Use `--task pipeline` to run the complete vendored mailroom graph. Each selected
class contributes `--samples` documents to the combined dataset. Reviewers stay
enabled; the computational report compiler remains deterministic and has no model.

API-only default:

```bash
sandbox experiment create pipeline-api --task pipeline \
  --provider openrouter --model qwen/qwen3.7-flash \
  --agent-model judge=deepseek/deepseek-v4-flash \
  --samples 10 --trace-sink langfuse
```

Modal/vLLM default with API agents (hybrid):

```bash
sandbox experiment create pipeline-hybrid --task pipeline \
  --model Qwen/Qwen3-8B-AWQ --gpu L4 --samples 10 \
  --agent-route sorter=openrouter:qwen/qwen3.7-flash \
  --agent-route judge=openrouter:deepseek/deepseek-v4-flash \
  --agent-route contracts_specialist=modal-vllm:Qwen/Qwen3-8B \
  --trace-sink langfuse
```

`--agent-model NAME=MODEL` changes a model on its current transport.
`--agent-route NAME=PROVIDER:MODEL` changes both. Routes override the global
provider, and explicit agent-model choices win last. Model/route selections are
locked and hashed; start/resume refuses configuration drift. The sandbox adapter
uses the same resolution seam for native and LangChain agents, so API credentials
are never borrowed for a GPU endpoint or vice versa. Unknown and retired agents
are rejected.

For a distinct endpoint, credential variable, GPU, or serving configuration, put
an explicit route in a file and pass `--agent-route NAME=@path/to/route.yaml`:

```yaml
provider: modal-vllm
model: Qwen/Qwen3-8B-AWQ
modal:
  app: sandbox-vllm-my-study-contracts
  gpu: L4
  max_containers: 1
  min_containers: 0
  scaledown_seconds: 120
  image_tag: v0.29.0
vllm:
  max_model_len: 32768
  quantization: awq_marlin
  max_num_seqs: 16
  enforce_eager: false
  enable_prefix_caching: true
```

Managed routes derive their URL from `MODAL_WORKSPACE` and `modal.app`. Share the
same app/configuration across agents to share a model deployment; incompatible
settings for the same app are refused. Shorthand routes with identical settings
share a generated app. All managed apps are sandbox-scoped and are stopped in
reverse order even when another deployment or smoke fails. Existing active apps
are refused rather than replaced or stopped.

An existing OpenAI-compatible endpoint uses `provider: vllm`, `model`, `base_url`,
and optionally `api_key_env`. A general API uses `provider: api`, `model`,
`base_url`, and a required `api_key_env`. OpenRouter defaults to
`OPENROUTER_API_KEY`. Store actual credentials in environment variables or `.env`,
not in YAML; route URLs reject embedded credentials/query parameters. Existing
`run start --config run.yaml --agent-route ...` also accepts these route choices;
`run resume --config ...` verifies them against the lock.

## Review, authorize, smoke, and launch

Copy `config/.env.example` to the checkout's `.env` and set the credentials and
`MODAL_WORKSPACE` needed by your routes. The CLI loads the checkout's root `.env`
first and then `config/.env`; exported environment variables take precedence over
both, and root `.env` takes precedence over `config/.env`. Both files are
gitignored. A route's `api_key_env` can name any valid environment variable: put
its value in either file or export it, and put only the variable name in YAML.
Local `HF_TOKEN` is used for local Hub access; managed Modal downloads use the
named Modal Hugging Face secret described in the template.

The selected trace
sink must be configured too: Langfuse is the default; `none`, explicit `otlp`, and
an optional Phoenix sidecar are available. Phoenix does not replace The-Mailroom's
Langfuse sink. Live tracing needs `pip install -e ".[observability]"`; the Modal
launcher requires the verified `modal==1.6.2` CLI.

```bash
sandbox experiment review --config config/experiments/pipeline-hybrid/experiment.yaml
sandbox experiment preflight --config config/experiments/pipeline-hybrid/experiment.yaml
sandbox experiment launch --config config/experiments/pipeline-hybrid/experiment.yaml
```

Launch displays every cell's complete settings, prepared row counts and hashes,
prompts, generation limits, models, routes, managed GPUs/replicas, deployment
environment, trace sink, and smoke/run budgets. It then asks for **2–6 initials**.
For a terminal without interactive input, explicitly supply `--initials JB` after
reviewing the output. There is no automatic `--yes` authorization.

Initials are a local operator attestation, not cryptographic identity verification.
The private `spend-authorization.json` receipt binds initials, time, the generation,
configuration, effective endpoints, and campaign smoke settings. Changed settings,
endpoints, re-locked data/prompts, or an expired receipt require a new signature.
The lower-level `run start`, `run resume`, and paid `run preflight --live` also
require a valid signed review. Mock endpoint runs do not require spend approval;
remote Modal workers still cost money even when their LLM calls are mocked.

Only after signing does the launcher prewarm/deploy, verify endpoints and served
models, and execute a **separate locked smoke dataset**. The default is one document
per specialist run; pipeline smoke covers one document per selected class.
`--smoke-rows` and `--smoke-cost-cap-usd` configure the smoke budget when creating
the experiment. A failed, missing, or partially processed smoke blocks the full
run. Every explicit route receives its own connectivity/chat check.

Cost caps are runtime estimates of GPU time, not hard invoice limits. Modal image
builds, CPU prewarm, cold boot, scaledown, concurrent replicas/model deployments,
and in-flight calls can add charges. OpenRouter is token-billed; the existing GPU
time cap is not an API dollar cap. The review names this distinction; configure
provider-side spending limits when a hard billing ceiling is required. Teardown
runs after each cell on success, failure, or interruption.

## Observe and analyze

In another terminal:

```bash
sandbox experiment watch --config config/experiments/pipeline-hybrid/experiment.yaml
sandbox board --probe-interval 60
```

The browser observer follows the campaign's `current-run` file as jobs change.
The services strip reads published doctor snapshots; periodic board checks stay
offline unless `--live` is explicitly supplied (live Modal probes can keep a GPU
warm). Full pipeline runs persist per-document evidence and update progress.

```bash
sandbox experiment report --config config/experiments/pipeline-hybrid/experiment.yaml
sandbox run status --config config/experiments/pipeline-hybrid/runs/<run-id>.yaml
sandbox run cancel --run-id <run-id>
```

`report.md` and `report.json` beside the manifest show successful/expected counts,
errors, configuration links, scorer aggregates, stored per-document score means,
and paired cell deltas when dataset bytes and complete coverage match. Incomplete
runs stay visibly incomplete. Native dated quality/serving artifacts remain under
`reports/`; the workflow never invents scores for missing documents. Re-running
launch rechecks locked configurations and skips completed jobs. A failed smoke
must be investigated and safely reset with the existing run lifecycle before retry.

For an offline end-to-end check, add `--mock --local-dataset FILE.jsonl
--trace-sink none` to create. The default tests use fake tools and local data; the
opt-in CLI contract checks in `tests/test_service_cli_smoke.py` do not deploy.
