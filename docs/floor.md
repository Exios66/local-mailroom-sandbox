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

## Sharing a digest

EXPORT downloads one JSON file of the digest on screen. IMPORT loads that
file, or a bare `floor_digest.json` from the builder, on another machine.
The file is the viewer contract: runs, scores, paths, debug traces, and the
graph reference. It is not `items.jsonl`, `nodes.jsonl`, or the other raw
run logs, and document text is not in it. The page reads the file with
`JSON.parse` and does not write the run store.

The file has `mailroom_floor_export` set to `1`, `exported_utc`, `focus`
(the run, class, debug filter, mode, document, and node on screen), and
`digest` (the same object as `floor_digest.json`). Focus also retains the active
drawer tab and document filters (confusion pair, outcome, class-miss toggle,
ID search and decision search). Import restores validated fields and clears
filters missing from older exports, preventing another viewer's selection from
carrying into the snapshot. A different export number, or a file that is not a digest, is refused
and the current view stays. The ribbon keeps SNAPSHOT beside the refusal. After import the ribbon says
SNAPSHOT and live polling pauses. A fetch that was already open does not
replace that snapshot when it returns. LIVE returns to the digest this page
opened with: the server digest over HTTP, or the `floor_digest.js` beside
the page for `file://`, retaining the current document filters. Imported node
focus must exist in the current graph and its displayed layout. A replay digest
stays labelled replay.

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
| DEBUG | Failure modes in the current filter, why the filtered documents reached the selected node, which of them repeat a node, and why they never recorded `archive`. Click a mode to isolate it, or a document row to trace it. |

## Debug mode

The ribbon **DEBUG** button isolates documents that need a diagnosis and
explains each hop from the trace that was stored. `?debug=1` opens it;
`?issue=` selects a filter (`problems`, `loop`, `stuck`, `held`, `failed`,
`open`, `miss`, `diverted`, `all`). The default filter is problems: still
open, held, failed, class misses, and any document that never recorded
`archive`.

The builder adds a `debug` object on each document row:

| Field | Meaning |
| --- | --- |
| `issues` | Tags from the trace: `loop`, `stuck` (open on a repeated node), `held`, `failed`, `open`, `miss` (a finished document whose predicted class differs from ground truth, including a ground-truth class with no predicted class, the same `unknown` the scores panel counts), `diverted` (no `archive` visit and not a ship outcome). |
| `loops` | Nodes entered more than once. `self` means the repeats were consecutive. `reentry` means the document left the node and came back. |
| `hops` | Each change of node, with a `why` sentence. A trace longer than 16 hops keeps the first eight and the last eight, with a `gap` row between them. That row is not a hop. |
| `archive` | Whether `archive` was visited, the node the trace stopped on, and why. |
| `mode` | One failure mode for the document, or null when nothing went wrong. `id` groups documents that failed the same way. `label` is the short name. `node` is the stage to inspect. `lever` names what to read before the next run. |
| `reads` | Present when the run recorded read ranges. `calls` (agent, node, `basis` working or raw, `ranges` as `[start, end)` offsets into the working text, matched and request counts, a `skipped` reason), `union` per agent, and `doc_chars` (the working text's length from the last working-basis call, null when none recorded one; a raw-basis call's length is never used). Numbers only. When the records carry a `text_hash`, `text_pairing` says whether the stored working text still hashes to it (`match`, `different`, `missing`); the hash itself is not emitted. See the document panel below. |
| `answers` | Stored decision phrases from the visits, for search. A phrase is omitted when the visit stored no decision. |
| `fields` | On the document row, not inside `debug`. Either stored Dojo `field_scores` below 1, or stored `extracted_data` set beside the dataset row. The comparison uses the full scalar; the quote is clipped at 40 characters. Empty when neither was stored. This list is not a new score. |

### Document panel: what each agent read

Select a document in DEBUG and the panel opens at the top of the DEBUG tab.
It answers one root-cause question: did the agent that had to extract a value
ever see the text that holds it?

- **Text.** The working text (what the pipeline actually read after intake) in
  a scrollable pane, with a **Working** / **Original** switch. A **rewritten**
  badge with the verbatim share appears when the working text differs from the
  dataset row's text. Read ranges index the working text, so the original view
  draws no bands.
- **Ranges.** One lane per agent in a minimap across the whole document, and one
  toggle per agent that paints its ranges on the text (specialists start on). An
  agent that ran more than once also gets a toggle per call. Only the last
  attempt's calls are kept: a resumed or retried document starts again at call 1
  and supersedes the earlier attempt, so those earlier calls do not appear.
  Overlapping agents show as stacked stripes. Calls made
  before intake finished were matched against the row's raw text; they appear
  as dashed bars and are never painted on the working text.
- **Colours** follow the figure roles of the `experiment-figures` skill: colour
  is the system, shade is the stage. The decision lanes (`decisions:*`) use
  decision-model blue, the sorter and its reviewer (`sorter_reviewer`) use
  LLM-sorter orange, specialists and their verifiers (`judge`, `arbiter`) use
  the third-system aqua, and `intake` and `jev` are neutral. The classification
  arbiter node runs on the `arbiter` agent, so its calls are the `arbiter` lane.
  An agent with no assigned colour gets the specialist, decision or neutral grey
  swatch.
- **Fields.** Every expected and extracted field, with a flag computed in the
  browser. The search is whitespace- and case-insensitive. Click a field to
  scroll to its occurrence; click again for the next.

| Flag | Meaning |
| --- | --- |
| `not read` | The expected value occurs in the working text, but in no range read by a specialist that ran for this document. Every call of those specialists counts, retries included. |
| `misrouted` | No specialist for the document's true class ran, so no field was extracted for that class. It replaces `not read`. A value absent from the text stays `not in text`. |
| `no specialist ran` | The document was classified as its true class, but no specialist ran for it, so no field was extracted. It is shown instead of `misrouted` when the predicted class equals the true class. |
| `not in text` | The expected value does not occur in the working text at all (a label or OCR difference, or a rewrite). |

"Specialist" comes from the digest: the agents seen under a graph node labelled
`specialists …` in the run's `node_agents`, plus any name ending `_specialist`.
A class is matched to its specialist by name (`contract` and
`contracts_specialist`); a document whose predicted class equals the true class
counts as routed to whichever specialist ran. When a specialist call has no exact
range (raw basis or a size skip), or the served text length differs from the
recorded working length (`doc_chars`; null skips the check), `not read` is not claimed and the panel says why.
When `text_pairing` is `different`, the stored text is from another attempt than the read ranges (a resumed run rewrote it, possibly to the same length), so the bands are withheld and no `not read` or `misrouted` flag is raised. Stores recorded before the hash existed have no `text_pairing` and keep the length check alone.
"matches" and "differs" beside an extracted value compare strings only. They
are not the Dojo score.

**Where the text comes from.** `debug.reads` in the digest holds offsets and
counts only. The text is served by the floor server at
`GET /api/floor/doc?run=<run>&doc=<doc>` on the loopback address, from the run
store the server was started on. Opened as a file, from a static host, as an
imported digest or for a replay run, the fetch is not made and the panel says
**text unavailable**; the lanes, toggles and call list still render from the
digest. A run recorded without `reads.jsonl` shows "not recorded for this run":
older runs, runs with `job.trace_reads: false`, and remote Modal runs until the job
worker is next deployed (unverified, a paid live step). See
[read ranges](jobs.md#read-ranges-jobtrace_reads) for the files and the switch.

**Privacy.** The digest, its JS twin and the export never contain document
text. The text stays in the run store and is shown only by the local server,
for the document you selected. The server answers only requests whose Host header is
`127.0.0.1`, `localhost` or `[::1]` on its own port (otherwise 403), so a web page on
another hostname cannot read it through DNS rebinding; reaching it through an SSH tunnel on a
different local port needs the same port on both ends. Do not share a screenshot of a real document;
the committed fixtures and tests use synthetic text only. Every control is a
native button, so Tab, Enter and Space work, and all document text is inserted
as escaped HTML.

A `why` sentence quotes only a stored decision, review cause, status, error,
or an unconditional edge (`plain_edges`, such as `catalog_write` to
`archive`). It does not re-run the routers. When the node record has no
decision, the sentence says so. A self-loop is not drawn; the node badge
`LOOP ×n` is the repeat count, and the right rail states what was recorded
on those visits.

Click a node while DEBUG is on for the arrivals into that node and the
documents that reached it instead of archive. Click a document for the hop
list. Older digests without `debug` keep the previous panels; rebuild to
fill the trace. Replay runs stay labelled as replay: the reasons describe
the scripted trace, not a live model.

Failure modes are the fine-grained groups inside a filter. A held document
is grouped by the node it stopped on and its recorded review causes, so
`class_miss` and `extraction_miss` stay separate. A stuck document is grouped
by the node and whether the repeat was consecutive or a reentry. A technical
failure is grouped by the node and the error token. A class miss that still
reached archive is its own mode. Click a mode to light only those documents.
`?mode=` deep-links one id. `?doc=` and `?node=` reopen a document or a node.
A selected confusion pair also controls clicked-node neighbors and the
selected-node count and the NODES table's docs column, alongside graph counts,
repeat badges and node diagnostics. Agent observations, p50, aborts and node
outcome summaries retain explicit run scope.
Pair counts and neighbors come from the retained document rows. If the builder
omits rows at its 5,000-row limit, the graph displays PARTIAL PAIR VIEW and the
rail and NODES table label their pair counts as retained docs. Omitted documents
can contain additional traffic and neighbors; these figures are not full-pair
totals. Clearing the pair restores the previous class and DEBUG filters.

`?cell=` reopens a confusion-matrix pair (`ground truth`, then a tab, then the
predicted class). Clicking a matrix cell isolates the documents in that pair
on the whole run, taking precedence over earlier class and DEBUG isolates. Lit edges follow each document's path, including hops the why list omits after 16. START and END use that same pair count. A selected mode lists its count in
every run of the digest, with the prompt stem stored for `mode.node` when the
lock has one. Copy note writes that mode, the count, the sample ids, the stem,
and the lever. It does not rewrite the run. A repeated visit shows stored
elapsed time and token counts when the node record had them, and says nothing
when it did not. Selecting a document lists that same id in the other runs of
the digest. The lever tells which stage to read. It does not rewrite
the run, its scores, or its prompts.

**Label tiers.** Ground truth comes from the Hub, then the interim overlay,
then the near-gold overlay (`interim_labels` / `near_gold_labels` on the run's
`dataset.jsonl` rows). A document is counted under the lowest tier that filled
any of its fields, so an extraction score that used a near-gold label is shown
as `near_gold`, never as a Hub-GT score. Rows from the repository's own
fixture manifest (`dataset: sandbox-fixtures`, used by `sandbox api eval` without `--dataset-config`) are
hand-written test labels and show as `fixture`, not `hub`. `class only` means the row labels the
class but no fields; `no GT row` means the run has no dataset row for it.

The digest keeps at most 5,000 document rows per run. Past that cap, problem
rows stay ahead of healthy archived rows. `docs_truncated` counts every row
left out, and `docs_omitted_healthy` counts how many of those were not
problems. Scores and node tables still cover every document. Mock and replay
runs carry a note: their numbers check wiring or the interface, not model
quality.

## API eval results on the floor

`sandbox api eval` can record its result as a floor run:

```bash
sandbox api eval --mock --floor-run api-mock --base /tmp/floor-base   # no server, no spend
sandbox floor api-mock --base /tmp/floor-base
```

`--floor-run [ID]` (default id: the eval's run tag) writes
`<base>/runtime/runs/<ID>/` with `items.jsonl`, `dataset.jsonl` (the eval's rows
without document text: fixtures, or corpus rows with their hub / interim / near-gold
tiers under `--dataset-config`), `checkpoint.json`, `spec.lock.json`
(`engine.kind: api-eval-mock` or `api-eval`, plus the `dataset` provenance under
`--dataset-config`) and `nodes.jsonl`. The API has no
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
