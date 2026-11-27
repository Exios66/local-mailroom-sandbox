# Jobs (DMR-027) — spec-driven, locked, resumable runs

The `sandbox run` system runs **pipeline evals as locked jobs**: every input —
prompt version(s) for any pipeline agent, the HF dataset (full mailroom-dataset
or a subset), the vLLM/Modal engine spec, and the OTEL trace sink — is
resolved, validated, prepared, and pinned at **preflight**; the job then runs
per item with crash-safe checkpoints, resumes after pause/failure, and can be
polled. Serving metrics from local, Modal, and API runs are captured and
compared.

```text
data/runtime/runs/<run_id>/
├── spec.lock.json       # immutable preflight manifest (the commit point)
├── prompt.lock.json     # per-agent resolved prompt + sha256 / Langfuse version
├── dataset.jsonl        # prepared subset (byte-identical per spec; hashed)
├── items.jsonl          # append-only per-item results (progress truth)
├── checkpoint.json      # atomic mirror (state/cursor/remote)
├── events.jsonl         # lifecycle journal (poll/pause/resume/fail)
├── reads.jsonl          # pipeline runs: one offsets-only record per LLM call (job.trace_reads)
├── doc_texts/           # pipeline runs: each document's working text + index.jsonl (run store; see Read ranges)
└── run.lock             # advisory local-filesystem writer flock
```

## Spec

`config/runs/examples/example.yaml` is the template. Key blocks:

```yaml
schema: sandbox.run/v1
run_id: <optional; auto ><task>-<model>-<utc>
task: sorter                # primary: specialist | pipeline (whole-run)
                            # per-item: sorter (resumable row-by-row)
                            # whole-run: pipeline | extract | chained | local_vs_api
                            #   | isolated (sorter spec) | ANY registered agent name
                            #   (e.g. judge, contracts_specialist — DMR-056: every
                            #   AgentSpec in eval/agents.py is a whole-run task; a
                            #   bogus task is rejected at spec parse, never "locks
                            #   prepared then dies")
target: null                # level 2 of specialist/pipeline: contract | merger_agreement
                            #   | corporate_record | correspondence | insurance_claim
                            #   (or the specialist name); unset = all five / every class.
                            #   `sandbox run … --target X` overrides it. Hashed only when set.
profile: vllm-local         # ollama | vllm-local | vllm-remote | modal-vllm | openrouter

prompt:                     # ALL pipeline agents: local variants + Langfuse + code
  default: {source: code-default}
  agents:
    judge: {source: local, file: judge_local_v0}
    sorter: {source: langfuse, name: mailroom-sorter, version: 9}   # integer pin
  versions:                 # eval-environment prompt versions (any _v0 / _v1 / mutation key)
    correspondence_specialist: correspondence_specialist_v3   # one role: `prompt.agents` OR `versions`

dataset:                    # full mailroom-dataset OR a subset
  provider: huggingface     # or file:/…/x.jsonl (offline)
  repo: Lucius-Morningstar/mailroom-dataset
  config: ground_truth      # labels + doc_text joined on filename
  split: all                # train+test (3,302 rows). `test` cannot back 40/100-per-class.
  revision: ed7576b676343e0b402ec5412cded301e629bdee     # pinned (no floating)
  strata:
    buckets:
      - {doc_class: contract, count: 40}          # or 20 / 100; merger max 152
      - {doc_class: corporate_record, count: 40}
      - {doc_class: correspondence, count: 40}
      - {doc_class: insurance_claim, count: 40}
      - {doc_class: merger_agreement, count: 40}
  limit: 200
  sample_seed: 42
  # OR name a registry entry (config/datasets.yaml) instead of the fields above:
  #   dataset: {name: pipeline-even100-shuffled2, limit: 50}
  # A file entry's local_path expands ${VAR} / ${VAR:-default} from the environment
  # (the CLI loads .env first; an unset MAILROOM_BASE_DIR resolves via the CLI's own
  # data directory); an optional sha256 pins the exact file and preflight refuses a
  # different one. The lock records the source sha always, the entry's `pull` only
  # when the entry sets one, and `name` only for named datasets; a sha-pin mismatch
  # is raised by prepare_subset and surfaces as a failed preflight `dataset` check.
  # $SANDBOX_DATASETS_REGISTRY selects a different registry file.

engine:
  kind: modal-vllm            # modal-vllm | vllm-local | vllm-remote
  model: Qwen/Qwen3-8B
  vllm: {max_model_len: 16384, gpu_memory_utilization: 0.90,
         max_num_seqs: 6, enable_prefix_caching: true, enforce_eager: true,
         quantization: "", revision: "", max_inputs: 4}
  # max_inputs: requests one Modal container admits at once (@modal.concurrent).
  # Default 0 serves one request at a time; preflight refuses a live modal-vllm
  # run with job.concurrency > 1 and max_inputs 0, since the GPU bills while
  # the other requests queue. Mock runs are not checked.
  # DMR-056: 16384 default — L4-bf16 8B-class rows cannot hold 32768 (v0.29.0
  # raises at boot when the KV pool can't fit one request); AWQ rows set 32768.
  modal: {app: sandbox-vllm, gpu: L4, image_tag: v0.29.0,
          scaledown_seconds: 120, max_containers: 1, min_containers: 0,
          prewarm: true}  # attended; restore 600 unattended (DMR-076)

job:
  mode: endpoint            # endpoint | modal
  mock: false
  max_retries: 2
  fail_fast: false
  concurrency: 4            # default JobSpec value — efficient conservative
                            # vs Modal vLLM continuous batching (docs: 4-16);
                            # set 1 explicitly for serial/CPU-Ollama runs
                            # — bounded to [1, 64] at spec validation
  cost_cap_usd: 1.00        # USD; estimated GPU spend (every warm Modal app) is
                            # checked before each document; the run then fails
                            # loud. An in-flight document is not interrupted and
                            # can take spend past the cap
  max_wall_seconds: 1800    # seconds (>= 60); checked the same way, before each
                            # document. The run then aborts and its fleet is torn down
  api_cost_cap_usd: 0.25    # USD; OpenRouter token spend (SAND-089), priced at the
                            # highest input/output price among the run's API models
                            # and checked before each document. Required when any
                            # agent bills tokens; every such model needs a price
                            # (config/api_prices.yaml, the built-in fallback
                            # SANDBOX_MODEL_PRICES in job/metrics.py, or both
                            # SANDBOX_TOKEN_PRICE_IN_PER_M and _OUT_PER_M) or the run
                            # is refused. Paid runs need max_wall_seconds, plus
                            # cost_cap_usd when they warm a Modal GPU and
                            # api_cost_cap_usd when they bill API tokens. `experiment
                            # create` fills unset ceilings from a recommendation.
  blind_routing:            # task: pipeline only; unset = true. The dataset labels
                            # (expected class and fields) stay out of the graph's
                            # state, so it neither routes on them nor scores itself
                            # against them mid-run (llm-mailroom #207); the sandbox
                            # scores afterwards against the full locked row. false is
                            # oracle routing: allowed only with job.mock (preflight
                            # refuses it for a live run, and a live override of a
                            # mock oracle lock is refused). Hashed only when true;
                            # an omitted pipeline value resolves to true and hashes
                            # the same as an explicit true. Other tasks resolve it to
                            # false (unhashed) and always run blind
  pipeline_handoff: false   # specialist tasks only. true sends each document the extract
                            # node's handoff (sorter-class line + the vendored
                            # doc_inventories note, no subclass) and applies the node's
                            # inventory normalization, so an isolated A/B sees what the
                            # pipeline's specialist sees (llm-mailroom #174). Hashed only when true
  trace_reads: true         # pipeline tasks: record which character ranges of each document
                            # every LLM call read (reads.jsonl + doc_texts/ in the run store;
                            # offsets only, no spans/Langfuse). Must be a boolean. Never
                            # hashed: it does not change what the run does

reviewer:                   # optional decision reviewer (SAND-085); see docs/experiments.md
  backend: api              # jev | local | api | mock
  model: openai/gpt-6-luna  # pinned: jev-X.Y.Z, the in-house model, or an OpenRouter id
  classes: {contract: 0.90, correspondence: 0.90}   # class -> cutoff in [0, 1]

extraction_gate:            # optional pipeline extraction gate (task: pipeline; Decisions-API model)
  model: openai/gpt-6-luna-decisions
  questions: extraction_gate_v1.3.0

decision_slots:             # optional llm-mailroom decision slots (task: pipeline). Every key but
                            # `resolver` is written verbatim to the runtime taxonomy's
                            # decision_slots: block and validated by the vendored mailroom at
                            # preflight (an older vendor without graph/decision_slots.py refuses a
                            # non-baseline block: re-vendor). archive_gate, judge_replacement,
                            # arbiter_veto, judge_check and boss_check need the extraction_gate
                            # block; reference: llm-mailroom
                            # docs/pipeline-reference-llm-mailroom/decision-slots.md. Caps count
                            # per process from a fresh ledger each run: a resume restarts them,
                            # and with job.concurrency > 1 which documents hit a cap depends on
                            # thread order. Mock runs never exercise the gate slots (the mock gate
                            # answers no field_support, so they record `unavailable`).
  archive_gate: {mode: enforce, park_cap: 0.10}
  closed_field_resolver: {mode: resolve, min_probability: 0.9, release_cap: 0.03}
  resolver:                 # needed when closed_field_resolver is not baseline; question set
    model: openai/gpt-6-luna-decisions   # frozen by content in the lock
    questions: closed_field_resolver_v1.0.0
                            # Each document exports decision_slot_outcomes / _marks,
                            # closed_field_resolutions and judge_source; `sandbox run gate`
                            # adds a decision_slots section (Dojo analysis.risk_coverage:
                            # per-slot rates and the gate key_field_score risk-coverage curve).

confidence:                 # optional run-scoped routing thresholds, merged over the
                            # vendored + overlay `confidence` block. Locked; hashed
                            # only when set. Calibrate per model: self-reported
                            # confidence scales differ by model. Evidence comes
                            # from `sandbox run routing`.
  arbiter_retry_max: 1      # global keys: high, low, judge_band_high (<= 1.01),
  judge_max_passes: 2       #   retry_max, arbiter_retry_max, judge_max_passes,
                            #   transient_retry_max, arbiter_full_source_min_confidence
                            #   (HF-014 floor, [0, 1]; unset: each class's `low`),
                            #   and the true/false flags judge_rejudge_retry,
                            #   judge_complete_archives, arbiter_accept_archives,
                            #   judge_clears_low_confidence, judge_exhausted_to_arbiter,
                            #   arbiter_full_source
  judge_rejudge_retry: false  # llm-mailroom #241, ships false: true re-judges a retry
                            # whose earlier attempt was judged, while judge passes remain
  judge_complete_archives: false  # llm-mailroom #309 archive checks (need the vendor refresh: the
                            # current vendored mailroom ignores them, so preflight refuses them); false keeps the checks on, true lets a
                            # judge `complete` (and an unjudged retry it doubted) archive as before;
                            # arbiter_accept_archives does the same for accept_with_caveats.
                            # judge_check / boss_check / arbiter_veto matter only where these are true.
  by_class:
    contract: {high: 0.95}  # live doc classes only; unknown classes fail preflight
    corporate_record: {judge_rejudge_retry: true}   # per-class override (E2 treatment arm)

trace:
  sink: langfuse            # langfuse | phoenix | otlp | none
  otlp: true
  environment: pilot
  tags: [sandbox, job]
```

## Dataset identity

See the [named-dataset reference](datasets/named-datasets.md) for registry
fields, examples, path/cache rules and the LM Studio demo's prerequisites.

A registry key is an alias for source and selection fields, not a content hash.
Preflight writes the exact normalized subset to the run's `dataset.jsonl` and
records its SHA-256, row count and actual class/subclass distribution at
`spec.lock.json` → `dataset.sha256`, `rows` and `strata_actual`. Those rows are
the evidence for which documents executed. A `limit` applies after filtering
and canonical sorting; shuffling source lines alone does not define the draw.

For local inputs, `dataset.metadata.sha256` is the hash of the original source
bytes read and parsed by preparation, which can differ from the prepared
subset's hash. `dataset.metadata.name` and `.pull` are recorded only when
supplied. For Hub inputs, inspect the requested and resolved revision alongside
repo/config/split. A local input's metadata identifies it as `source: local`
and `revision: offline`; the lock's top-level revision fields are not proof
that a local file came from that Hub revision.

Local-file `spec_hash` uses the filename and source-byte SHA-256 when the file
exists, plus `limit`, `sample_seed`, `strata` and `exclude_expected`.
`require_task_gt: true` is also hashed for both local and Hub datasets, because
it filters out rows with no task ground truth before selection. Its false
default is omitted, preserving unfiltered hashes. A filter change must refuse
resume with `drift_refused`; relocking preserves the previous generation.
`dataset.exclude_ids_file` (repo-relative text file, one document `id` per line, `#`
comments and blank lines ignored) drops those rows before any draw, so nested slices
stay nested. Its content sha256 is hashed as `exclude_ids_sha256` only when set; a set
but missing file fails preflight, and the `dataset` check reports `excluded=<matched>/<listed>`.
The registry name, declared SHA pin and pull
recipe are not hashed. Same-named identical files hash alike across checkout
paths. Missing files still hash without source bytes; this does not mean they
can pass preflight. Older path-based local-file locks drift under this scheme.
Filename portability alone does not change Hub-dataset hashes; the task-GT
filter fix changes hashes for previously filtered specs of either provider.
Inspect drift before choosing `--force`,
which archives an eligible generation and creates a replacement lock.

`sandbox hf download` populates raw Hub snapshots. `sandbox datasets pull`
materializes the normalized corpus JSONL used by the default offline sampler.
`sandbox datasets prepare` cleans fixtures, while run preflight locks a
specific run's subset. These are separate operations. See the
[Hugging Face skill](../.cursor/skills/huggingface/SKILL.md) for pins and cache paths.

## CLI

```bash
sandbox run preflight --config <run.yaml> [--offline] [--live] [--dry-run]
sandbox run start      --config <run.yaml> [--mock|--local] [--job-mode endpoint|modal] [--watch]
sandbox run status     --run-id <id> [--watch] [--json]
sandbox run resume     --config <run.yaml> --run-id <id> [--force]
sandbox run cancel     --run-id <id>
sandbox run list
sandbox run routing    --run-id <id> [--quality-target 0.7]   # offline routing audit
sandbox run gate       --run-id <id> [--prev-run-id <id>] [--bars <yaml>] [--thresholds] [--json]  # offline slice gate; writes gate.json/gate.md; exit 0 pass, 2 fail, 1 error

sandbox prompts list                       # every pipeline agent prompt (local + Langfuse)
sandbox prompts show <agent> [--variant X]
sandbox metrics compare --runs a,b[,c]     # local / Modal / API comparison
sandbox metrics compare --log
```

Exit codes: `0` done · `1` failed · `2` paused · `3` drift/busy/foreign-store refusal.

Two preflight guards keep a run's lock honest about what ran (SAND-104, #312):

- **Unknown keys fail.** Every run-spec section rejects keys it does not know, so a typo, or an older checkout that predates a key such as `dataset.exclude_ids_file`, fails validation instead of silently drawing a different slice.
- **The `checkout` check.** It fails when the imported `mailroom_sandbox` code lives in a different git checkout from the one the run is launched from. That happens in a worktree whose `.venv` links to the main checkout. Fix it with `export PYTHONPATH="$PWD/src"`, or set `SANDBOX_ALLOW_FOREIGN_CHECKOUT=1` to accept it deliberately. A cwd outside any git checkout passes. The lock records the code's checkout as `package: {path, commit}`, next to the cwd's `git` snapshot.

`sandbox run gate` has its own exit codes: `0` pass, `2` a FAIL verdict, and `1` with a JSON `failed` status when the gate cannot judge the run (the run is missing or never started, the bars file is invalid, or the scorer fails). The slice loop it gates (preflight → start → gate → fix → re-run → step up) is in [`docs/runbooks/production-slices.md`](runbooks/production-slices.md).

**Routing audit.** `sandbox run routing` reads a finished store and reports, per
class:

- how often each escalation fired: `retry_classify`, judge, arbiter, re-extraction, review;
- **yield**: whether a retry ever changed the class answer or improved the judge verdict;
- **discrimination**: the scored quality of judged vs unjudged and parked vs archived documents;
- judge/arbiter input cost at the vendored 16k window and at full coverage.

It lists findings, such as a judge that never passes, retries with no yield, a
`high` above the sorter's confidence ceiling, or low-quality classes that skipped
the judge. It also suggests a `judge_band_high` from the recorded
`extraction_confidence` once five or more scored documents carry one. These are
evidence, not settings. Apply them through the run's locked `confidence` block,
then confirm with the next run's audit. Preflight's `context_plan` prices the
longest document of each class three ways: a clean pass, one judged pass, and
the worst-case loop the thresholds allow (four judge calls per pass and node run: each judge asked once more
after a parse failure; transient re-runs are not priced). Each figure includes the intake read of
the class's costliest document whose intake gate fires; the plan's `intake` block
counts every gated document (`docs_gated`, `calls`, `input_usd`). It prices windows HF-010 would refuse on an API
route, so it errs high there, and a gated document on an unpriced intake model makes the envelope null.
Item records carry `pred.intake` (`gate_fired`, `read_failed`, `prior_sent`, ...); `gate_fired` is true when a prep
is present or the gate would have fired although the call raised.

A matching repeated preflight validates the committed dataset hash, prompt lock,
checkpoint and spec identity and leaves all generation artifacts byte-identical,
including remote call identity. Missing/drifted artifacts fail rather than being
silently rebuilt. It does not repeat live probes for an existing generation.
Preflight shares the endpoint runner's local filesystem writer lock and returns
`busy_refused` immediately when that lock is held. A worker's Volume copy of
`run.lock` is separate: Modal Volumes do not support distributed file locks.
Remote reset protection uses the checkpoint's call ID and a result-path
completion check, never the local flock or a diagnostic call graph.

`--force` is a generation reset. It refuses a running local checkpoint or a
remote call whose completion cannot be proven, even if the local writer lock
is free. For Modal SDK 1.6.4, a nonblocking `FunctionCall.get(timeout=0)` result,
remote execution timeout, terminated-result error or expired output with no
unfinished inputs permits reset. Pending polls, transport/lookup failures and
ambiguous exceptions refuse reset. A terminal-looking checkpoint or call graph
alone is insufficient. Cancel and wait for a paused endpoint or a proven
terminal remote call first. An eligible reset
archives the lock, dataset, items, prompts, checkpoint, events, cold-boot
measurement, worker-local experiment log and cancellation controls together in a unique archive directory.
It does not terminate remote work or bypass foreign-store ownership guards.

Each execution process restores the locked profile, engine model, explicit
`agent_models`, complete `agent_knobs` map and frozen prompt texts/selections.
Existing eval runners' subsequent activations obey that policy too. CLI
`--model`/`--agent-model` selections become lock/spec identity at start;
`agent_models: {judge: model-id}` can also be specified in YAML. Empty maps
preserve legacy spec hashes. Run-id-only resume refuses runtime overrides that
differ from the lock; use a config and a safe explicit reset for new choices.
Provider endpoint URLs and credentials remain operator environment settings.

For a running row-resumable `sorter` endpoint task, `run cancel`
writes `cancel.request.json` without waiting for the runner's lock and reports
`cancel_requested`. Prepared, paused and terminal local runs report their
current state without creating a pending token. The runner marks `running`
before the first provider submission, so a first-row cancellation still drains
and pauses correctly. A separate short `cancel.lock` serializes control writes
and generation resets without taking the runner lock. The runner checks before
each submission, drains all
submitted calls, persists their results, then acknowledges the token in
`cancel.ack.json` and writes `paused`. The checkpoint remains `running` while
calls drain. Resume ignores an acknowledged token, skips completed indices and
runs the remaining rows; a newer token cannot be erased by an older
acknowledgement. A provider call already submitted can still finish, so pause
latency includes its duration. Whole-run delegates retain their existing
whole-run granularity; this row-level cancel protocol does not reach those
evaluators (their resume replays finished documents instead, as described below). Remote `FunctionCall.cancel` behavior is unchanged.

A resumed `pipeline`, `specialist`, `isolated` or agent-name task replays the
documents an earlier attempt persisted in `items.jsonl`. Each is scored again
from its stored answer, with no model call and no new spend, so run scores still
cover every locked document and only the rest run and are billed (S1,
`docs/design/specs/2026-11-26-correcting-judge-design.md`). A document whose
stored item has no answer (`pred` not an object) or failed (`error` set: a
timeout, a 5xx, a guard refusal) runs again, as before, so a resume can recover it;
its first row stays the evidence in `items.jsonl`. An answer that failed to parse
is a billed answer and is replayed.
`extract`, `chained`, `local_vs_api` and `sorter_vs_modernbert` persist nothing
mid-run, so they still run whole.

A recovered valid JSONL final record may lack LF; the next append supplies its
separator. Completed per-item summaries and score error counts cover all stored
indices, including earlier invocations. Quality metrics continue to score only
successful predictions, with their own explicit denominator.

API-evals terminal reuse validates the requested spec/prompt/dataset lock and
requires an exact run ID (or exact legacy experiment name) and spec hash in the
record. Substring matches and stale scores cannot satisfy a changed request.
New records also stamp `run_task` from the immutable lock before append,
retaining the evaluator's `task` (`isolated` delegates to `sorter`; `chained`
to `extract`). Both fields are validated: a foreign scorer task cannot pass
by carrying a correct run-task stamp. Legacy records require exact task,
full prompt SHA, dataset fingerprint, bounded time and an unreset legacy lock.
Matching reuse still needs no API key; missing matching evidence fails loudly.

## Preflight

The sandbox `.env` and `config/.env` load before prompt resolution, endpoint
probes, trace credential checks or knob capture, without activating the runtime.
Explicit environment values take precedence. Cold execution still restores
locked prompts/models/knobs rather than later ambient generation settings.

1. **prompt** — resolves every agent override (local file sha256, Langfuse
   pushed integer version id, or code default). Unknown agents fail closed.
2. **dataset** — pinned-revision parquet (`default`+`ground_truth` joined on
   `filename`), `content_sha256 == sha256(doc_text)` verified per row, then
   deterministic subsetting (sorted by filename/id, per-stratum sub-seed
   draws, union, re-sort, `limit`). `file://` paths short-circuit all Hub
   calls. Idempotent: same spec → byte-identical `dataset.jsonl`.
   `pipeline`, `specialist` and `*_specialist` runs also get an advisory
   **context_plan** (`report["context_plan"]`), including on a repeat preflight
   of an existing generation. It never fails preflight. It runs on the taxonomy
   the run would activate (overlay plus the same run `agent_knobs` snapshot the
   lock freezes) over the rows the runner executes (`target` applied), and
   reports three things. First, specialist chunk windows per extraction pass,
   counted with the vendored paragraph-aware splitter; an isolated specialist
   run on Modal, vLLM or another self-hosted route chunks only when it has a
   `chunk_chars` knob, otherwise it is one truncated pass. On an API route
   (OpenRouter or any hosted provider) a specialist never chunks (HF-009): it
   ignores `chunk_chars`, reads the whole document in one `extract` call, and
   a document over its input budget fails with `WholeDocumentTooLong`. The
   pipeline sends that failure to review; an isolated evaluation records an
   item error. Second, for `pipeline` runs, how much of each class's longest
   document the judge and the arbiter each see on their own windows: the
   vendored `JUDGE_SOURCE_CHARS` / `SOURCE_CHARS`. Without context fit,
   `agents.judge.max_input_chars` does not change them. On a context-fitted
   route each agent's window becomes the larger of its own final budget (run
   knobs included) and the vendored value: a run override can raise a window
   but never lower it below the vendored 16k, and the judge and arbiter
   budgets apply independently. Third, rows under
   200 characters. Overlay specialist budgets
   are sized for a 16k-token L4 window. **Context fit** (`context_fit` in
   `config/taxonomy.overlay.yaml`) resizes specialists, `judge` and `arbiter`
   on an `openrouter` route to the model's `context_length` from
   `config/api_prices.yaml`. It also raises the chunk cap and the judge/arbiter
   source windows. API specialists refuse input beyond their budgets
   (`WholeDocumentTooLong`, HF-009). On an API route, sorter and intake refuse
   input that needs more than one window (HF-010). Judge and arbiter
   source excerpts are outside those hotfixes and can still truncate long
   input to their fitted windows; intake failures keep the clerk output. On
   an engine of `qwen/qwen3.5-9b` the fitted windows are 2,487,552 characters (judge, which the
   profile serves on `deepseek/deepseek-v4-flash`, a 1,048,576-token context) and
   600,115 (extraction and classification arbiters, on qwen), above the specialist's
   570,624, so any document that passes extraction reaches all three whole;
   `tests/test_openrouter_full_source.py` checks a 250k-character document
   end to end and that Modal/vLLM stays at 16,000. A document longer than the
   arbiter window but inside the specialist budget (another model) is still
   excerpted for the arbiter. An acceptance from an excerpted reading parks only while the
   extraction is still unsure — confidence missing or under the class `low` band with no
   source-verified judge verdict — and archives at or above the band. An acceptance from a
   whole-source reading archives (HF-014) even below that band when the extraction confidence
   reaches `confidence.arbiter_full_source_min_confidence`; unset, that floor is the class's
   own `low` band, where the vendored route already archives, so HF-014 changes no route until
   a run lowers it (for
   example to 0.5). The floor can only lower the bar: one above `low` changes
   nothing, because the vendored route already archives at `low`. Modal,
   vLLM, Ollama and LM Studio routes keep the 16k posture and the vendored
   chunking.
   The plan reports what was fitted under `context_fit`, and run `agent_knobs`
   still win. Preflight also records `expanded_inputs`: each context-fit reader,
   its live `max_input_chars`, and whether that length was swapped on. An API
   reader the run calls that is still on the short Modal/L4 budget, or whose
   model has no `context_length` in `config/api_prices.yaml`, fails preflight
   by default: HF-009 would otherwise reject every longer document mid-run.
   An isolated task counts only its own readers (`sorter`: intake, sorter and
   sorter reviewer; an agent task such as `judge`: that agent); `pipeline` and
   the other multi-agent tasks count every reader.
   Two cases stay ok. One is a specialist or other reader's input-budget gap when the run YAML sets
   that reader's `max_input_chars` in `agent_knobs` (a posture default does not
   count). The knob never excuses a short judge or arbiter source window, nor a
   judge or arbiter whose model has no `context_length`: that reader would also
   keep the 16k source excerpt. The other is a decision-model task
   (`sorter_reviewer`, `extraction_gate`) on a non-chat reviewer backend, which
   calls no reader. `job.require_expanded_inputs` or `--require-expanded-inputs`
   fails the first case too. A fitted specialist's output cap is raised only
   when the model's window still holds the run's own `max_input_chars` beside it. A Modal or local route has nothing to swap.
   `sandbox run preflight --agent-knob NAME.key=value` sets the same generation
   parameters a run YAML's `agent_knobs` block does, including `max_input_chars`.
   The check uses the provider and model recorded for each reader, including when
   context fit is turned off, so an OpenRouter route on a local profile is still
   required to be wide. One `--agent-knob` overrides that key only. On a
   posture-managed run with no YAML knobs, the posture's other budgets stay. A new lock freezes that fit
   (`context_fit.sha256`). The digest covers the fitted windows, the chunk cap,
   whether chunking is enabled, and the overlap. Resume, including
   `sandbox run resume --run-id`, refuses before any document when the price
   sheet or overlay would change any of those. The digest also covers a fitted
   specialist's raised output cap (`context_fit.output_tokens`). An OpenRouter
   lock taken before that cap existed is refused on resume only when its fitted
   specialist output cap now rises (the digest changes), and then needs `--force`
   to re-lock; one whose digest still matches resumes as it is. A lock without the key
   still resumes when its spec hash matches, on the live fit. A lock without a
   frozen `effective_confidence` resumes on the retry budgets it started with
   (`routing_audit.legacy_thresholds`), not on keys a later overlay added. Re-preflighting a slice whose YAML now sets
   `require_expanded_inputs` changes `spec_hash`, so a `--config` resume returns
   `drift_refused` until `--force` archives that generation and re-locks. Production
   slices set `job.require_expanded_inputs`. Their sorter and intake stay at
   600000 characters on purpose; the other readers use the fitted room. The
   published API caps were estimated on the older chunked posture, so a
   whole-document reader can spend more than `api_cost_cap_usd` and should be
   re-measured before a paid slice.
   See
   [the Qwen-25 failure-mode audit](audits/2026-11-15-pipeline-qwen-flash-25-failure-modes.md).
3. **engine** — vLLM field/range guards (DMR-022 flags, v0.29.0 rules) +
   optional live `/v1/models` probe (`data[0].id == spec.model`) with `--live`.
   `run start --job-mode modal` probes the engine before firing (DMR-048).
4. **modal** — GPU/image/`max_containers` guards.
5. **trace sink** — OTLP contract resolved (Langfuse `/api/public/otel`,
   Basic auth + `x-langfuse-ingestion-version: 4`; Phoenix `/v1/traces`;
   generic `OTEL_EXPORTER_OTLP_ENDPOINT`).
6. **lock** — `spec.lock.json` written LAST (the commit point) with
   `spec_hash` over the behavioral core. Resume refuses on drift unless
   `--force`. The lock also pins `revision_resolved` + `prompt_text_sha`; a
   prompt-text change refuses (DMR-049), and `dataset.sha256` is re-verified
   at worker start and at resume — drift refuses (exit 3) unless `--force`
   re-locks and archives the old generation.

The engine step also refuses a live `modal-vllm` run whose `job.concurrency` is
above 1 while `engine.vllm.max_inputs` is 0 (mock runs are not checked). The
reviewer gets its own checks: `local` must be in-house and a different model from
the sorter, `api` needs an OpenRouter `sorter_reviewer` route, and `jev` is refused
for mock runs and Modal jobs.

## Loop governor (`job.governor`)

Phase 2 of the [correcting-judge design](design/specs/2026-11-26-correcting-judge-design.md) gives a
`task: pipeline` run one budget per document across every node, so a document stops at a recorded outcome
instead of looping until the hard call ceiling (40) refuses it. It is off unless the job sets it, and it is
refused for any other task. `governor: true` takes every default; a mapping sets fields:

```yaml
job:
  governor:
    retries: 2                 # rounds per document: classify and extraction retries, arbiter calls, boss entries
    calls: 30                  # model calls per document (1-39, below the hard ceiling of 40)
    calls_by_class: {merger_agreement: 36}
    spend_usd: null            # off until the pilot measures cost per type
    sorter_ceiling: null       # L2: a classify retry at or above it goes to the second opinion
    near_empty_chars: 64       # L5: shorter known text goes to review before any model call (0: off)
    link_duplicates: true      # L4: exact or near copies of archived documents are linked, not escalated
    near_duplicate_jaccard: 0.9
```

Before each step that would add a round, the governor checks, in order: a second boss entry
(`boss_repeat`), the retry budget (`retry_budget`), the call budget (`call_budget`) and the spend budget
(`spend_budget`). A second re-extraction counts as a round; a node re-run for a transient error does not.
A stopped document goes to human review. It is archived with caveats (`archive_with_caveats`) only when its
latest recorded extraction attempt has a `complete` judge verdict and the judge tail's own archive guards hold
(no lost chunks, confidence at the low band or a source-verified verdict, no unadjudicated matter conflict);
a stopped boss entry is never archived. Transient provider errors keep their own limit
(`transient_retry_max`) and still count toward the call and spend budgets. With L1, every HTTP attempt on
the chat, LangChain and Decisions paths counts, a failed one included (a request the guard refused never
went out and does not count). A successful reply that carries no usage is the exception: it is not counted,
because a missing usage block cannot be told from a cache hit that made no request. Cost is reserved only
for guarded (OpenRouter) requests while a budget is armed. The call budget is checked before each round, so a round that starts below it
can still end above it; the hard ceiling stays the backstop. The mechanics are vendor hotfixes HF-018 and
HF-019 ([vendor hotfixes](vendor-hotfixes.md)).

L4 links a near copy only when every archived value that differs from the new extraction appears in the new
document's text: a re-scan read differently. When one does not, the documents differ where the fields do
(template siblings with other parties or dates) and the conflict goes to the Boss as before. L5 reads the
text the materializer would: non-empty inline `doc_text` or `text`, else a text fixture; a binary or missing
source is left to the pipeline.

Each item that the governor touched records it, and a run without the governor gets none of these keys:

- `governor_stop`: `{reason, outcome, node, proposed, calls, retries, spend_usd}` for the first stop
  (`near_empty` stops at `node: intake` with no model call);
- `duplicate_of`: `{doc_id, kind, similarity}` when HF-019 linked a duplicate (`kind` exact or near);
- `governor_skips`: `{classify_retry: n}` when L2 skipped a sorter retry.

The gate report adds a `governor` block (stops by reason and outcome, duplicates by kind, skipped sorter retries
and the documents), and a review the governor sent is typed `governor:<reason>` (`input:near_empty` for L5).

The block is part of the hashed spec when set (not when absent), and HF-018 and HF-019 are in every lock's
`vendor_hotfixes`, so a run locked before this change refuses resume until `--force` (a generation reset; see
[Checkpoint / resume](#checkpoint--resume)). The near-duplicate index is in-process: near copies are found among
the documents this process has seen in the run.

## Subclass extraction schemas (`job.subclass_schemas`)

Phase 3 of the [correcting-judge design](design/specs/2026-11-26-correcting-judge-design.md) (X1,
"narrow and extend"). **Always on for `task: pipeline`**: subclass schemas are used whenever one is
available. Leaving `job.subclass_schemas` unset turns it on for pipeline runs and off for every other task.
An explicit `false` on a pipeline run is refused, and `true` on another task is refused. Every extraction is
sent the schema of the document's **predicted** subclass instead of the whole class schema.
This applies to all five classes: contract (by `contract_subtype`), merger agreement, corporate record,
correspondence and insurance claim (by `doc_subclass`).

The schemas come from a committed file, `config/extraction/subclass_extraction_fields.json`. It is derived
from the label registry `config/extraction/subclass_schemas.json` by `python scripts/build_subclass_fields.py`
(`--check` fails when stale, and `tests/test_subclass_fields.py` checks it too). Every subclass of every class
has an entry:

- **drop**: class fields the vendored Dojo never scores as a value for the subclass (status
  `not_applicable`, `absent_from_dojo` or `documented_absent`), unless a dev, calibration or pool label gives
  the field a value there (the registry's `valued_by_set`). The scorer counts a labeled value, so dropping
  that field would turn a hit into a miss. Today the drops are:
  - contract, every subclass: `maud_clauses` and `merger_consideration`;
  - merger agreement, every subclass: `intent`, `keywords` and `subject_matter`;
  - insurance claim: `cms_source_table` on `auto` and `property`, plus `adjuster` and `denial_reasons` on
    the CMS subclasses and `property`;
  - corporate record: `filing_number` on four subclasses, plus `jurisdiction` and `signatories` on
    `subsidiary_list`.

  Held-out labels never keep a field. The one held-out `filing_number` value on `bylaws` is therefore not
  asked for, and scores as a miss on that one held-out document. A subclass's own `output_schema_fields` in
  the registry, when present, replaces the class's.
- **add**: fields outside the class schema with dev, calibration or pool labels and an extraction status.
  Today there are none: the corporate entity fields have no labels yet, and correspondence `content_topic`
  and `sentiment_label` are label tasks, not extraction fields.
- **guide**: the labeling-guide text. It replaces a kept or added field's description only when
  `job.schema_guide` is also on, and never a description `schema_guide` curates. Today every registry guide
  entry names a curated field, so the curated text is what the model sees.

Held-out labels never shape a list: only the `dev`, `calibration` and `pool` counts are read.

The class schema is kept when the predicted subclass is missing, `unknown`, `other` or not listed, or
when `classification_confidence` is missing or below the class's `low` band. The sorter reports no
separate subclass confidence.

For pipeline runs the switch and the file's sha256 are hashed into `spec_hash`. At activation the runtime
refuses a field list whose sha differs from the locked one, so re-run preflight after rebuilding it. HF-023
applies the choice: one specialist instance serves one document's extraction and every chunk window, and it
alone is given the narrowed schema. HF-024 keeps the review consistent with it: the judge's expected-field list and the
extraction the judge, the arbiter and the retry summary read leave out the dropped fields (and list the added
ones). The next document, and a fallback extraction, see the class schema. A confidence that is missing, NaN or not
a number falls back.
A corporate specialist whose `extract` another hotfix wraps (a dedicated corporate schema composer) keeps that
hotfix's schema; the other classes are unaffected. HF-023 changes the hotfix set, so a run whose lock records a
set from before it is refused on resume; re-lock it with `--force`, and the new pipeline lock turns subclass
schemas on. A lock from before the hotfix layer records no set and has no `subclass_schemas` key, so when it
resumes it runs with class schemas. Preflight resumes it only while it has no checkpoint, and a direct run
refuses it once work has started. An ad-hoc pipeline eval
with no lock uses the committed field lists.

## Read ranges (`job.trace_reads`)

A `task: pipeline` run records which character ranges of each document's working
text (the text after intake) every LLM or decision call contained, so the
[floor viewer's DOCUMENT panel](floor.md#document-panel-what-each-agent-read) can
show whether the agent that had to extract a value ever saw it. It is on by
default; set `job.trace_reads: false` to turn it off. The key must be a boolean and
is never hashed, because recording does not change routes, scores or costs. With it
on, each pipeline item in `items.jsonl` gains a small `reads` block of counts
(`read_calls`, `read_errors`, `read_ms`) and nothing else about the item moves.

The recorder reads the value from the run's lock, not from the YAML. Because the key
is not hashed, editing it on an already prepared run does not change the lock: a
re-preflight still says `prepared` and adds a `trace_reads` check naming the value
the lock keeps. To apply the new value, re-lock with `preflight --force`, which
archives the whole generation (finished items, `reads.jsonl` and `doc_texts/`
included). A lock written before the key existed counts as `true`.

- `reads.jsonl` gets one line per call:
  `{doc, call, agent, node, ts, basis, ranges, request_chars, matched_chars, doc_chars}`
  plus `unplaced_pieces`, `skipped` when matching was skipped, `ranges_approx` when more
  than 64 disjoint matches forced the smallest gaps closed (a merged range then also spans
  unread text, so the ranges locate approximately what was read — `matched_chars` stays
  exact), and, on working-basis
  calls, `text_hash` (sha1 of the working text's UTF-8 bytes, first 16 hex characters). `ranges` are
  half-open `[start, end)` offsets into the working text. There is no text in it.
- `doc_texts/<sha1(doc)[:16]>.txt` holds each document's working text. The last write
  wins: a resumed document replaces the file (atomic rename, bytes written as UTF-8
  with no newline translation). `doc_texts/index.jsonl` maps the document id to the file
  name and to the same `text_hash`, one line per document: a rewrite with different text
  replaces the line, and a line lost in a crash is added again on the next write. The
  floor digest recomputes the hash from the stored file and withholds the bands when it
  differs from the records' (an attempt that rewrote the text and died before reading).
  `debug.reads` also carries that stored file's own `text_hash`, which the document panel
  compares against the tag of the text the endpoint serves (refetching once per digest
  generation on a mismatch, then keeping the response with its bands withheld).
  Where the text goes: into the run store (`data/runtime/runs/<run_id>/doc_texts/`), and
  from there to the floor server's loopback endpoint for the document you select. A
  remote Modal job also copies `doc_texts/` to the Modal volume with the rest of the run
  directory and pulls it back (the same volume already holds `dataset.jsonl`, which has the
  same text). No code path puts it into Langfuse or other trace spans, `items.jsonl`,
  `nodes.jsonl`, logs, the floor digest or its export, or git.
- A call made before intake finished is matched against the dataset row's raw text
  and marked `basis: "raw"`. A document above the matcher's size limit is not
  matched (`skipped: "size"`).
- A request is recorded once the call guard lets it go out (`job.api_cost_cap_usd` and the
  per-document call ceiling): a call the guard refuses never shows as read, and a retry
  inside one logical call counts once. Calls on a route with no guard are recorded when
  the call returns or fails.
- Chat agents record only the document-bearing part of the request: the user message
  plus a system prompt passed as a plain string. `request_chars` and `matched_chars`
  are measured over that portion, not the full request on the wire. Decision requests
  mask card numbers, which show up as small gaps in the ranges.
- `unplaced_pieces` counts the request's blank-line pieces of at least 12 non-whitespace
  characters that could not be placed — not in the document, the per-request uniqueness
  budget spent, or the piece's gap too large to scan — so such a request is shown as
  partly measured rather than fully covered. A capped call (`ranges_approx`) keeps
  `matched_chars` exact but its merged ranges span unread text.
- A pipeline run's `nodes.jsonl` now also carries records for documents that reach
  `classification_arbiter`, which was not tracked before, whether or not
  `job.trace_reads` is on. That node runs on the `arbiter` agent, so its records
  name `arbiter` and that agent's model, and its chat reads are recorded as `arbiter`.
- Remote (Modal) runs upload and pull `reads.jsonl` and `doc_texts/`, but the job
  worker records them only after it is next deployed. Until then a remote run shows
  "not recorded". Unverified: that redeploy is a paid, live step.
- Run stores made before this feature show "not recorded for this run".

## Checkpoint / resume

- `items.jsonl` is the progress source of truth; `checkpoint.json` is the
  atomic mirror. On every load the torn tail is truncated and the cursor is
  recomputed from items (self-healing).
- `run_job` appends one `items.jsonl` row per item (index, expected,
  predicted, ok/error, latency, ts), then writes the checkpoint.
- Ctrl-C → `paused`; errors retry up to `max_retries`; `fail_fast` marks
  `failed` (with `concurrency > 1` it stops *scheduling* new rows; in-flight
  rows finish and persist — their GPU work is already spent). `resume` of a
  per-item task never re-runs completed rows: it skips by completed **index**, so concurrent
  runs whose items completed out of order resume exactly (the old
  contiguous-cursor skip would silently drop rows).
- **`concurrency: N`** (job block, `[1, 64]`) runs N rows in parallel so a
  vLLM endpoint's continuous batching fills up — offline evals are a
  throughput workload (Modal `vllm_throughput` exemplar). Workers only
  compute; every RunStore write and progress event happens on the main
  thread, and each row runs in a copied context so the pipeline's
  contextvar run limits and trace state stay per-doc isolated.   Recommended:
  4-16 against a Modal-hosted vLLM (JobSpec default is **4** — the efficient
  conservative sweet spot); set `concurrency: 1` explicitly for CPU Ollama or
  per-item latency-sensitive runs.
- **Modal mode**: immutable lock content identifies the complete generation,
  including its UUID, prompt text and dataset bytes. A new upload uses
  `/runs/.generations/<lock_sha256>/<run_id>` on `sandbox-runs`, with no
  `--force`; mismatched legacy directories are left untouched. An exactly
  matching original `/runs/<run_id>` directory remains resumable. Deploy the
  updated worker before dispatching this protocol; old worker images do not
  understand the new path/expectation payload.
- Spawn expectations and worker progress/terminal values carry the exact
  generation identity. The worker reloads its mounted view before checking
  the expectation, validates before activation, and commits terminal artifacts
  before publishing terminal state. Dict keys include lock content identity.
  Stamped runs reject unstamped/stale terminal caches. Old-format worker
  progress needs a matching legacy lock and a heartbeat after lock creation.
- Terminal pulls validate the fetched lock, dataset, prompt, checkpoint and
  transferable JSON/JSONL in staging before changing local artifacts. Malformed
  diagnostic `nodes.jsonl` rows are skipped with a warning in the staging copy,
  matching `RunStore.iter_nodes`; corrupt results, lifecycle records or generation
  identity still refuse the pull. The remote source remains unchanged. Local
  immutable files and writer/control lock inodes stay intact. Finalization
  imports only matching run/spec/generation/task records; a refused pull makes
  status/watch fail instead of reporting completion.
- Resume attaches to a known matching live call. Re-fire requires an expired
  cooldown and result-path proof of termination; unknown status fails closed.
  These checks are not a distributed dispatch lease. Two independent clients
  without a shared recorded call ID can still race to dispatch the same
  generation, as in the baseline worker. Serialize control operations for one
  run across clients; different runs remain independent. This proposal adds
  no atomic lease or unsafe stale-owner takeover. Interrupted no-force uploads
  can require operator recovery after confirming no live writer.

## Remote GPU (Modal)

```bash
# build/deploy the worker once (installs the sandbox package + dojo + otel)
cd deploy && modal deploy modal_job.py
# run
sandbox run start --job-mode modal --config <run.yaml> --watch
```

For long Modal **endpoint** evals against `sandbox-vllm`, use the full mailroom watch
TUI (in-tray + postage + `modal app logs -f`) in a second pane or browser tab —
see **[pretty-logging/mailroom-themed-logging.md](pretty-logging/mailroom-themed-logging.md)**. `sandbox run … --watch`
only streams job progress lines, not vLLM dispatch logs.

The worker runs the same checkout code on a CPU container against the
Modal-hosted `sandbox-vllm` endpoint (the GPU is the serve app), or against
OpenRouter for an `engine.kind: openrouter` run (#308). For that, deploy the
worker with `OPENROUTER_API_KEY` exported: it travels in the deploy Secret, and
the worker removes it from any run that never calls OpenRouter. Preflight and
`sandbox run start` also need the key in the launching shell for an OpenRouter engine or a
non-mock `decisions` reviewer, even when a different shell deployed the worker. The `decisions`
reviewer is supported in modal mode; the `api` and `jev` reviewers are not. It emits
OTEL job/item spans to the locked sink. In-container vLLM (GPU job) is a
documented follow-up.

- `run start --job-mode modal` probes `/v1/models` first (skipped for
  mock/`--offline`) — a stale `VLLM_BASE_URL` fails fast as
  `engine_unreachable` (DMR-048).
- Whole-run tasks (`pipeline`/`extract`/`chained`/agent names) score the
  LOCKED dataset rows when preflight prepared any (Hub or local) — a Hub
  spec + `task: pipeline` runs the connected graph on live corpus rows
  (DMR-056); an empty lock falls back to the runners' fixture defaults.
- Worker failures land in the state dict with `error`, `traceback_tail`, and
  runtime `diagnostics`; `SANDBOX_DEBUG=1` enables DEBUG logging in the
  container — export it BEFORE `modal deploy` (it travels through the deploy
  Secret; DMR-056); `modal run modal_job.py --debug` prints the app config
  (DMR-053).
- Whole-run records are stamped `prompt_version` (the lock's LOCAL variant
  stem), `spec_hash`, `dataset_fingerprint`, `run_id`; delegated runs used to
  mislabel every record `mailroom-default` (DMR-053).

## Metrics: local vs Modal vs API

`job/metrics.py` builds dojo-compatible serving records from run stores:

- per-item (`items.jsonl`): `latency_ms`, and when the live OpenAI-compatible
  response exposes usage — `prompt_tokens`, `completion_tokens`, `llm_calls`;
  `ttft_ms` only when recorded (never inferred from e2e);
- per-run: n, mean e2e/ttft, prompt/completion tokens, tokens/s, `model`
  price from `price_for` / sandbox champion table, `estimated_cost_usd` +
  `cost_per_document` when the price table knows the model;
- Modal / vLLM GPU attribution: `gpu_seconds` × configurable L4 rate
  (default ≈ `$0.80/hr`, env `MODAL_GPU_USD_PER_HOUR` /
  `MODAL_GPU_USD_PER_SEC`) → `estimated_gpu_cost_usd` +
  `gpu_cost_per_document`. Prefer `MODAL_BILLED_GPU_SECONDS` when you have a
  warm billed window; else sum of ok-item `latency_ms` (busy-time lower bound).
  Missing tokens/GPU seconds omit the $ fields (loud warning) — never silent `$0`;
- `sandbox metrics compare` buckets by profile (`local`/`modal`/`api`),
  aggregates each bucket, computes deltas vs API (latency, ttft, throughput,
  token $, GPU $), runs dojo `compare_serving` pairwise (local↔api,
  modal↔api, local↔modal), and prints a markdown table.
- Regenerate a committed serving artifact from a live run store (no Modal spend
  on regen — reads `data/runtime/runs/<run_id>/` only):

  ```bash
  sandbox metrics serving-record --run run-20-correspondence-awq-c8
  # → reports/serving/run-20-correspondence-awq-c8.serving.json
  ```

  Wall clock comes from item `ts` spans when present; pass `--wall-seconds` when
  the store lacks timestamps (historical runs). Measured run stores are not
  committed — reproducing byte-identical committed JSON requires the original
  `items.jsonl` + lock under `data/runtime/runs/`.
- Offline Grant-style parity (no Modal secret):
  `sandbox metrics compare --fixture`. Adapter
  (`mailroom_sandbox.eval.serving_parity`) converts `latency_ms`/`ttft_ms`,
  stamps champion token $ for `Qwen/Qwen3-8B`, and checks sandbox rows
  against `get_suite("local_vs_api")`. Dojo still remaps identity
  `serving_kind=modal` → `local` (two-bucket suite); GPU $ stays sandbox-only.

### Sorter vs ModernBERT

```bash
sandbox eval sorter_vs_modernbert --mock
sandbox metrics compare --sorter-vs-modernbert
sandbox metrics compare --sorter-vs-modernbert --runs <sorter-run>,<modernbert-run>
```

Fixtures: `data/fixtures/serving/sorter_vs_modernbert.json`. Compares
accuracy / F1 / latency / `$/doc` between the LLM sorter and the trained
ModernBERT ingest classifier (mailroom-ml / Corpus-EDA).

Live feeder (no weight copies into the sandbox):

```bash
export MAILROOM_ML_SRC=/Users/morningstar/Desktop/Cold_Storage/mailroom-ml
export MODERNBERT_MODEL_PATH=$MAILROOM_ML_SRC/artifacts/run2-published
sandbox modernbert status
sandbox modernbert eval --sample 50 --json
sandbox eval sorter_vs_modernbert --local   # live ModernBERT + sorter fixture/log
```

### Cost extrapolation

```bash
# Pre-flight (no Modal spend) — specialist 5×30 suite defaults (scaledown 120)
sandbox metrics estimate-suite
sandbox metrics estimate-suite --scaledown-seconds 600 --json  # unattended what-if

# Post-run (needs items.jsonl + lock)
sandbox metrics extrapolate --run run-30-contracts-specialist \
  --corpus-size 3302 --docs-per-day 10000
```

See [`docs/runbooks/README.md`](runbooks/README.md) for the Modal L4 Qwen specialist
suite (singular 1×L4 / 1-container) and improved configs. Catalog:
[`config/runbooks/catalog.yaml`](../config/runbooks/catalog.yaml). CLI:
`sandbox runbook show l4-qwen3-8b`.

### AWQ vs FP16 isolation (issue #21) — config only, do not run

[`config/runs/legacy/run-20-correspondence-fp16-c8.yaml`](../config/runs/legacy/run-20-correspondence-fp16-c8.yaml)
is the FP16 twin of `run-20-correspondence-awq-c8`: same seed-42 correspondence
draw (fingerprint `285f423d3708`), same local prompt, concurrency 8, targeting
`Qwen/Qwen3-8B` (non-AWQ). The live quality compare is **blocked until
spend/auth go**. Do not `modal deploy` / `sandbox run start` this YAML from the
diagnosis PR.

When an operator is cleared to run it: `sandbox runbook show improved-correspondence-fp16-c8`.
Confirm the lock fingerprint is `285f423d3708` before scoring. Diagnosis of the
AWQ floor (no GPU):
[`docs/archive/extraction-quality-diagnosis.md`](archive/extraction-quality-diagnosis.md).

TTFT is only populated when a run records it (never inferred from e2e).
Document-pipeline eval traces follow the locked `trace.sink`: `langfuse` or
`phoenix` sets the vendored pipeline's SDK to that sink, while `otlp` and
`none` turn the pipeline SDK off (`otel.pipeline_provider`). Job, preflight and
item spans travel over OTEL (job spans only).

## Tests

The job surface is covered by network-free suites. The commands below are a
test map: choose a focused file for local investigation, with one worker and
no coverage. Full-suite and coverage verification belong to hosted CI; see
[CI gates and resource policy](../.circleci/README.md).

```bash
uv run pytest tests/test_job_spec.py
uv run pytest tests/test_job_checkpoint.py
uv run pytest tests/test_job_preflight.py
uv run pytest tests/test_job_runner.py
uv run pytest tests/test_job_otel.py
uv run pytest tests/test_job_remote.py
uv run pytest tests/test_job_metrics.py
uv run pytest tests/test_job_cli.py
uv run pytest tests/test_corpus.py
uv run pytest tests/test_prompt_registry.py
uv run pytest tests/test_api_budget.py
```

### Generation integrity

New locked generations carry a unique ID alongside the existing spec hash.
Initial operator generation knobs and resolved prompt bytes are frozen at
preflight. Every execution entry checks dataset, prompt and checkpoint identity
before activation; resume uses the frozen prompt even if its local stem changes.
A missing or damaged artifact refuses execution. An eligible explicit force reset
archives the old generation; API result reuse requires successful evidence from
the current generation and task. Complete old-format evidence retains a narrow
compatibility path; unproven historical records cannot silently become current.

## Dependency provenance

New run locks freeze both family source choices in `dependency_sources`. Status
reports those original choices; preflight reuse and execution refuse dependency
drift, including edits/additions/deletions under installed or vendored source
roots whose version/commit metadata stayed fixed. Source digests include resources
and executable modes, ignore generated bytecode, and use relative paths so matching
worker copies stay portable. Select release caches before process startup and bundle the same snapshots
into remote job images. See [stable dependency snapshots](dependency-snapshots.md)
for selection, verification and recovery. Older locks remain readable.
