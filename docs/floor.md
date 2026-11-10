# Pipeline floor viewer

`sandbox floor` rebuilds a digest from run artifacts and serves the pipeline
viewer at `http://127.0.0.1:8769/floor.template.html`. Run it from an editable
repository checkout: the builder and HTML assets live in `reports/dashboard/`.
It requires no model server, API key or tracing service.

```bash
sandbox floor                                      # history, or bundled replay if no runs exist
sandbox floor my-run --base /path/to/mailroom-data  # preselect a run in that store
sandbox floor --run my-run --interval 2 --port 8769
sandbox floor --replay --base /tmp/mailroom-floor-demo
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

A run is discoverable when its directory contains `items.jsonl` under either
store location. The refresher checks modification times and sizes of
`items.jsonl`, `nodes.jsonl`, `checkpoint.json`, `spec.lock.json`,
`prompt.lock.json` and `dataset.jsonl`, plus the run directories. It skips a
rebuild when that signature is unchanged. It writes derived
`reports/dashboard/floor_digest.json` and `floor_digest.js`; it does not rewrite
historical run inputs. Replay mode also writes its own sample run.

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

Class views use the run's `per_class` data. A missing or incomplete class label
must not leave figures from a previous selection visible. Missing dataset
labels are unknown, rather than measured routing failures. The graph is read
from the vendored `build_graph.py` using AST parsing; viewing it does not run
the pipeline.

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
output does not copy the HTML viewer. `FLOOR_DIGEST_GRAPH` overrides the
builder's graph source; use the vendored source for normal runs. Restart a
resident viewer after changing graph or builder code because those files are
not part of the run-artifact sweep.

| Symptom | Check |
| --- | --- |
| Expected run absent | Confirm `--base`, the run directory and `items.jsonl`; a target only preselects discovered runs. |
| No changes in a completed view | Reload; browser polling follows a selected running run. Check artifact timestamps and `generated_utc`. |
| Port already in use | Choose another `--port`, or use `--port 0`. |
| Sample reset refused | Use a fresh scratch base; preserve the conflicting directory for inspection. |
| Missing builder or viewer | Use the repository checkout with `reports/dashboard/` present. |

The standalone builder returns 2 for no runs, 3 for an invalid graph and 4
for output-write failure. `sandbox floor` propagates builder diagnostic exit
codes, returns 2 for CLI usage errors and 1 for failures such as unavailable
replay assets or binding the server port. Ctrl-C exits normally.

For changes to this feature, use focused fixture tests locally and inspect
the full hosted gates described in [CI guidance](../.circleci/README.md).
