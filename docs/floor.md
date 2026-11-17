# Pipeline floor viewer

`sandbox floor` rebuilds a digest from run artifacts and serves the pipeline
viewer at `http://127.0.0.1:8769/floor.template.html`. The builder and HTML
assets live in `reports/dashboard/`, supplied by the repository checkout and
the offline Docker image. A wheel-only install needs those assets too.
It requires no model server, API key or tracing service.

```bash
sandbox floor                                      # history, or bundled replay if no runs exist
sandbox floor my-run --base /path/to/mailroom-data  # preselect a run in that store
sandbox floor --run my-run --interval 2 --port 8769
sandbox floor --replay --base /tmp/mailroom-floor-demo
sandbox floor --replay-run data/runtime/runs/my-run   # recorded run from any provider
sandbox floor --replay-run my-run --base data --replay-speed 20
```

Open the printed URL yourself; Ctrl-C stops the server and replay worker.
The bind address is always `127.0.0.1`. The dashboard directory is served, so
keep access local when the run data contains sensitive metadata.

## Options and run discovery

| Option | Behavior |
| --- | --- |
| `TARGET` or `--run ID` | Preselect a run by ID; all discovered runs remain available. Supplying both with different IDs is a usage error. |
| `--base DIR` | Data-store root, with `run-history/` and `runtime/runs/` beneath it. Defaults to `MAILROOM_BASE_DIR`, otherwise `<repo>/data`; `~` is expanded. |
| `--port PORT` | Default 8769; 0 requests an available port, reported in the printed URL. |
| `--interval SECONDS` | Digest rebuild check interval, default 5 seconds. Must be finite and positive; values below 0.1 are clamped to 0.1 seconds. |
| `--replay` | Create/reset the owned sample run inside the chosen base and play its simulated trace alongside history. |
| `--replay-run PATH_OR_RUN` | Materialize a recorded run from any provider as an app-owned replay and play its node/item timeline. A bare run id is resolved under the base's live or history store. |
| `--replay-speed N` | Timeline multiplier. Default 1x for `--replay`, 10x for `--replay-run`; use a higher value for long recorded runs. |

A run is discoverable when its directory contains `items.jsonl` under either
store location. The refresher checks modification times and sizes of
`items.jsonl`, `nodes.jsonl`, `checkpoint.json`, `spec.lock.json`,
`prompt.lock.json` and `dataset.jsonl`, plus the run directories. It skips a
rebuild when that signature is unchanged. Each resident viewer writes
`floor_digest.json` and `floor_digest.js` in its own temporary directory and
serves those at the root digest URLs alongside the dashboard assets. Viewers
using different bases or ports cannot overwrite one another's digests, and
the temporary files are removed on exit. Shared dashboard snapshots and
historical run inputs are unchanged. Replay mode also writes its own persistent
sample run inside the selected base; viewers sharing that base still see the
same run artifacts.

Port 8769 is separate from web/watch (8765/8766) and board/demo (8767/8768).
See the [watch guide](pretty-logging/mailroom-themed-logging.md) for document
logs and the [job guide](jobs.md) for starting or resuming real runs.

## Live refresh and navigation

The viewer selects the latest running run when available, otherwise the last
run in the digest. Deep links accept `?run=<id>&class=<live-class>`; a class
must exist in that run. Changing runs or refreshing a digest clears an
unavailable class and updates the title and mode together. Valid run, class
and highlighted-node selections survive refreshes.

Over HTTP(S), a selected running run polls the digest every 3 seconds, with
one follow-up poll after it becomes idle. Node elapsed clocks tick each
second while documents remain in flight. The server's `--interval` controls
digest rebuild checks, independently of this browser polling interval.
Completed-only views stop polling; reload to discover later runs. A `file://`
view is a static snapshot without live pills, clocks or polling.

Three consecutive fetch failures mark the view stale while retaining its
last data. Use the digest's `generated_utc` to assess its age. A later rebuild
failure logs the error and keeps the previous good digest available for a
retry; a failed initial build prevents startup.

## Reading the figures

| Display | Meaning |
| --- | --- |
| Node count | Distinct documents that entered the node, including those that subsequently left. |
| RUNNING pill | Documents currently in that node, with elapsed time; the pill uses run-wide in-flight data even in a class view. |
| Edge count | Recorded traversals; self-loops are not drawn. |
| Progress | Checkpoint cursor versus total; complete runs show 100%. |
| AVG | Mean of finite per-document elapsed times, displayed as minutes/document; it is not total run wall time or throughput. |
| Ground-truth routing | Match fraction against available ground truth, not the sorter's confidence. |
| HELD / human review | Parked review documents; technical runtime failures belong in FAILED. |
| Routed to human review | Documents routed for review, split by classification, extraction, judgment or reporting trigger; resolved reviews can still contribute. |
| Dashed audit arrows | Stage-audit side effects parsed from `_emit_stage_audit` call sites in the vendored graph, rather than workflow edges. The review arrow carries the routed count. |
| Prompt card | Per-run stems from `prompt.lock.json` for the highlighted node's agents, with code-default fallback when unavailable. Deterministic nodes do not imply an LLM call. |

A run whose checkpoint still says `running` but whose `items.jsonl`,
`nodes.jsonl` and `checkpoint.json` have not changed for 15 minutes is shown
as **stalled ⚠** (a killed process never rewrites its checkpoint). The digest
keeps the original value as `checkpoint_state`, the idle time as `stalled_s`
and `last_activity_utc`; a stalled run gets no RUNNING pills and is not chosen
as the default run, but the browser keeps polling it so a resumed run comes
back. While any checkpoint says `running`, the resident app rebuilds the digest
at least every 60 seconds even with no artifact change, so a run that dies
while the viewer is open turns stalled. `FLOOR_STALL_SECONDS` changes the
threshold.

Class views use the run's `per_class` data. A missing or incomplete class label
must not leave figures from a previous selection visible. Missing dataset
labels are unknown, rather than measured routing failures. The graph is read
from the vendored `build_graph.py` using AST parsing; viewing it does not run
the pipeline.

## Analysis panel: scores, documents and nodes

The panel under the graph (hide or show it with its toggle) follows the
selected run and the isolated class.

| Tab | What it shows |
| --- | --- |
| SCORES vs GT | Classification accuracy over documents with a ground-truth class that finished (a finished document with no predicted class counts as a miss, shown as `unknown` in the confusion matrix; an open one is not counted yet); the mean Dojo `overall_extraction_score` over all label tiers, with the Hub-GT-only mean beside it; the near-gold fields used; outcome totals. A per-class table (recall, precision, extraction mean, near-gold documents, archived/review/failed/open; click a row to isolate the class), the label-tier table and a confusion matrix (rows ground truth, columns predicted). |
| DOCUMENTS | One row per document: GT and predicted class (✗ on a miss), outcome, extraction score, label tier, review trigger, latency and node path. Filter by outcome, by misclassified-or-failed, or by id. Click a row to light only that document's path on the graph and show its details in the right rail. |
| NODES | Per node: documents in, p50, aborts, where those documents ended up (archived/review/failed/open) and how many were classified right. Click a row to select the node. |

**Label tiers.** Ground truth comes from the Hub, then the interim overlay,
then the near-gold overlay (`interim_labels` / `near_gold_labels` on the run's
`dataset.jsonl` rows). A document is counted under the lowest tier that filled
any of its fields, so an extraction score that used a near-gold label is shown
as `near_gold`, never as a Hub-GT score. Rows from the repository's own
fixture manifest (`dataset: sandbox-fixtures`, used by `sandbox api eval`) are
hand-written test labels and show as `fixture`, not `hub`. `class only` means the row labels the
class but no fields; `no GT row` means the run has no dataset row for it.

The digest keeps at most 5,000 document rows per run (`docs_truncated` counts
the rest); scores and node tables still cover every document. Mock and replay
runs carry a note: their numbers check wiring or the interface, not model
quality.

## API eval results on the floor

`sandbox api eval` can record its result as a floor run:

```bash
sandbox api eval --mock --floor-run api-mock --base /tmp/floor-base   # no server, no spend
sandbox floor api-mock --base /tmp/floor-base
```

`--floor-run [ID]` (default id: the eval's run tag) writes
`<base>/runtime/runs/<ID>/` with `items.jsonl`, `dataset.jsonl` (fixture rows
without document text), `checkpoint.json`, `spec.lock.json`
(`engine.kind: api-eval-mock` or `api-eval`) and `nodes.jsonl`. The API has no
per-node trace, so each document's path is rebuilt from its stage audit
(`GET /audit/{doc_id}`): nodes that write no audit entry, such as
`compile_report` and `catalog_write`, are missing from those paths. An
existing run id is refused before anything is uploaded. `--base` defaults to
`MAILROOM_BASE_DIR`, then the repository's `data/`.

## Recorded replay from any provider

`--replay-run` replays a recorded run; it does not care whether the run
was served by Modal vLLM, OpenRouter, Ollama, LM Studio, a remote host or a
local vLLM process. The source is read-only and needs only the run artifacts:

| Artifact | Use |
| --- | --- |
| `items.jsonl` | Document outcomes and classes. Required unless `nodes.jsonl` exists. |
| `nodes.jsonl` | Node starts/finishes, durations and per-document routes. Required for the live timeline. |
| `checkpoint.json` | Terminal state/cursor/total shown by the viewer. |
| `spec.lock.json` | Provider/model/profile provenance; the original `engine` block is preserved verbatim. |
| `dataset.jsonl`, `prompt.lock.json` | Optional labels and prompt identities. |

The importer builds a timeline from source timestamps. If a run has no usable
timestamps it falls back to document order and labels the replay **synthetic
timing**; a source that never reached a terminal state is labelled incomplete.
The replay is written under
`<base>/runtime/runs/replay-recorded-<source>-<hash>` with empty
`items.jsonl`/`nodes.jsonl` and its own `replay.jsonl`; the driver appends the
recorded events in real time. The viewer shows the original provider/model and
a `recorded replay (...)` note in the run outcome line, so replayed evidence is
never mistaken for a live result. Other history stays selectable and untouched.

Ownership and hardening: a symlinked source or artifact is refused, artifacts
over 100 MB each or 250 MB total are refused, malformed JSONL rows are skipped
with a warning, a timeline over seven days is refused, and an existing run is
never replaced: a new suffixed replay id is allocated instead. A bare id
resolves to the base's live or history store. Use `--replay-speed` to compress a long run; the default
is 10x for recorded runs and 1x for the bundled sample.

Bundled resets require a bundled-mode ownership marker or the exact identity
of the committed legacy sample. An arbitrary `engine.kind: replay` lock,
including a recorded replay, never authorizes deleting a run.

```bash
sandbox floor --replay-run data/runtime/runs/pipeline-modal-1
sandbox floor --replay-run /tmp/exported-run --base /tmp/floor-base --replay-speed 50
```

## Bundled replay and ownership

The [sample provenance and files](../data/fixtures/floor/replay/README.md)
describe 120 public document IDs and metadata, 24 per live class. No document
text is included. Decisions, scores, token counts and latencies are simulated.
The roughly 66-second trace includes concurrent arrivals, technical failures,
parked human reviews and a resolved classification review that re-enters
extraction. Use it for UI verification, never as experiment evidence.

The sample is written to
`<base>/runtime/runs/replay-mailroom-sample` and persists after shutdown. Only
that sample directory resets on another `--replay`; other history stays
selectable. With no target and no discovered runs, the command starts this
replay automatically when the bundled fixture exists. An explicit target
does not trigger that fallback.

Reset accepts an empty directory or a valid replay-owned lock. A symlinked
sample directory, foreign run, malformed lock or unknown nonempty directory
is refused. Choose a fresh scratch base instead of deleting operator data
to bypass the ownership check.

## Building a snapshot and troubleshooting

For a one-shot digest, without a resident server:

```bash
python reports/dashboard/build_floor_digest.py --base /path/to/mailroom-data --print-summary
# Optional: --out /path/to/derived-output
```

The builder writes JSON and JS using separate atomic replacements. Custom
output does not copy the HTML viewer. Unlike the resident app, this one-shot
command leaves its digest files at `--out` (default `reports/dashboard/`) for
later static viewing. `FLOOR_DIGEST_GRAPH` overrides the
builder's graph source; use the vendored source for normal runs. Restart a
resident viewer after changing graph or builder code because those files are
not part of the run-artifact sweep.

| Symptom | Check |
| --- | --- |
| Expected run absent | Confirm `--base`, the run directory and `items.jsonl`; a target only preselects discovered runs. |
| No changes in a completed view | Reload; browser polling follows a selected running run. Check artifact timestamps and `generated_utc`. |
| Port already in use | Choose another `--port`, or use `--port 0`. |
| Sample reset refused | Use a fresh scratch base; preserve the conflicting directory for inspection. |
| Missing builder or viewer | Use the repository checkout or a rebuilt offline image with `reports/dashboard/` present. |

The standalone builder returns 2 for no runs, 3 for an invalid graph and 4
for output-write failure. `sandbox floor` propagates builder diagnostic exit
codes, returns 2 for CLI usage errors and 1 for failures such as unavailable
replay assets or binding the server port. Ctrl-C exits normally.

For changes to this feature, use focused fixture tests locally and inspect
the full hosted gates described in [CI guidance](../.circleci/README.md).

Replay runs are view-only: run preflight/start/resume/status/cancel refuse them,
including forced re-locks. Use `sandbox floor` to inspect or replay these copies;
provider metadata describes the source and cannot dispatch its job.
