# Per-agent read ranges and the floor document inspector

Status: approved by the owner 2026-11-25 (rev 2, normalised working text) · approach A chosen by the owner · 2026-11-25

## Why

Root-cause analysis of a failed document needs two things the floor viewer lacks:

- **The document itself.** The text the pipeline worked on, in debug mode, beside the hops and field
  scores.
- **What each agent saw.** The trace records which nodes ran and what they decided, not which part
  of the document each agent read. A specialist can miss a field because the value was never in its
  window, which is a window or budget problem. It can also miss a value that was in its window,
  which is a prompt or model problem. Today nobody can tell the two apart.

## Goals

1. Every LLM and decision-model call made during a pipeline document records which character ranges
   of the document text its request contained. No text goes into the call record.
2. In floor debug mode, a selected document opens a **document inspector**:
   - the text the agents worked on;
   - each agent's read ranges as coloured bands, toggled per agent and per call;
   - every field's expected and extracted value, with where each occurs;
   - a flag on each field whose expected value appears in no range its specialist read.
3. Recording never changes routing, scores, prompts, requests, costs or locks. It cannot fail or
   noticeably slow a document.

## Non-goals

- No prompts, responses or document text in `nodes.jsonl`, `items.jsonl`, `reads.jsonl`,
  `floor_digest.json`/`.js`, the digest export, Langfuse or anything committed. This is why B was
  rejected.
- No edits to `vendor/` or `vendor_hotfixes.py`. This is why C was rejected.
- No PDF rendering: the corpus has no PDFs (rows carry `doc_text` only). A link to a readable local
  source file is a small follow-up if one ever exists. *(My call.)*
- No new scoring.

## Anti-goals: a result that technically works but fails

- Run results that differ with recording on and off: items, scores, routes, costs, lock digests.
- Document text reaching the digest, the export, Langfuse or git.
- A recording error that surfaces as a failed or slower document.
- **False "not read" flags.** A flag on a value the agent did see, caused by whitespace, markup or
  rewriting differences, would defeat the feature.

## Approaches considered

| | How | Trade-off |
|---|---|---|
| **A (chosen)** | At the call seams, match each request against the document's **working text** and store `[start, end)` ranges per call | Small, offline, no text in call records; matching against the working text avoids false gaps |
| B | Store full requests | Exact, but heavy and puts text in run stores and traces |
| C | Vendor hotfix on the window cutter to log offsets | Exact for cut windows only; misses judge, arbiter and decision requests; edits pipeline behaviour |

## Key decision: measure against the working text, not the dataset row

Agents never see `doc_text` verbatim. The pipeline first normalises it at intake:

- markdown stripped;
- Unicode normalised;
- CRLF converted to LF;
- runs of spaces and blank lines collapsed;
- line ends trimmed;
- hyphenated line breaks joined.

See `vendor/llm-mailroom/src/graph/build_graph.py:593-597` and `agents/intake.py:61-71`. For messy
or mid-size documents, the LLM intake agent's cleaned output then replaces the text for every later
agent (`build_graph.py:640-668`). Matching against the raw row would leave gaps wherever the text
changed, with 0.45–1.0 verbatim coverage on the fixtures, and those gaps would produce false
"not read" flags.

So **ranges are measured against the document's working text**: the text in graph state after intake,
which is what every later agent's window is cut from.

- The runner captures that text once per document from the intake node's output.
- It is written to the local run store as `doc_texts/<doc>.txt`. That store is gitignored local
  runtime state, and it already holds the raw text in `dataset.jsonl`.
- The digest and the export never contain it.
- The inspector shows the working text with the bands. A toggle shows the original row text, without
  bands.
- When the intake LLM rewrote the document, a badge says so and gives the verbatim overlap with the
  original. *(My call: this is the only way the flag can be trusted.)*

## Design

### Recording (runtime)

- **New module** `src/mailroom_sandbox/job/read_ranges.py`. It holds a per-document `ContextVar`
  (doc id, working text, and a shingle index built lazily once the working text is known), the
  matcher, and a sink.
- **Document scope:** `eval/runners.py:_process` enters it beside `track_nodes` for pipeline documents,
  only when a node sink is set (the same condition as node tracking).
- **Working-text capture:** `NodeTracker.on_chain_end` already receives node outputs. When the intake
  node's output carries the working text, the tracker hands it to the read-range context. Calls made
  before that, such as the intake agent's own request, are matched against the raw row text and marked
  `basis: "raw"`. The builder finds the exact state key.
- **Call seams.** These are thin observers: they read the outgoing request and pass it on unchanged.
  Any exception inside one is swallowed and counted.
  1. **Chat agents:** wrap `_call_structured` on both definitions (`agents/base.py:203`,
     `langchain_agents/base_agent.py:471`). Install the wrapper **unconditionally and outermost**, above
     `sampling.py`'s wrapper, because on the LangChain path with extra knobs that wrapper skips the
     original method (`sampling.py:237-240`). It records `agent_name`, `system_prompt` and
     `user_message`. This covers the intake agent, sorter, reviewer, specialists, judge, extraction
     arbiter and classification arbiter.
  2. **Decision backends:** `_post_decision` (`decision_backends.py:716`) is where every Decisions
     request passes. The Jev backend's pydantic_ai call (`decision_backends.py:129-172`) is wrapped
     separately.
     - These requests mask card numbers (`:675`, `:777`, `:1148`), so the masked spans show up as small
       gaps. That is documented, and the masking itself is unchanged.
  - `pdf_transcriber` and `image_extractor` send images and are not recorded.
- **Node attribution:**
  - Each record carries `agent`, `ts`, a per-document call index, and the tracker's innermost open
    node when there is one.
  - `classification_arbiter` (and intake, if missing) is added to `NODE_AGENTS` (`job/node_trace.py:47-61`),
    so its visits appear in `nodes.jsonl` and in the floor path. This is an **intended** change to
    `nodes.jsonl` for documents that reach that node: today its calls are invisible.
- **Matcher:**
  - It finds maximal verbatim substrings of the working text inside the request: fixed-length shingles
    at a stride over the working text, extended in both directions on a hit, with overlaps merged.
  - Each call stores:
    - `ranges`: doc-absolute in the working text, merged, capped in count;
    - `basis`: `working` or `raw`;
    - `request_chars`;
    - `matched_chars`: request characters covered by ranges. A low share means the request held text
      not taken verbatim from the document, such as handoff context or masked digits.
    - `doc_chars`.
  - Windows cut by `sliding_windows` are exact slices of the working text and match exactly.
    `extract_chunked` uses `_split_chunks` (`specialist_agents.py:868-902`), which drops
    whitespace-only paragraphs and rejoins chunks with `"\n\n"`. Its chunks therefore come back as
    several adjacent ranges that cover their paragraphs, which is still exact per paragraph.
  - Matching is skipped above a configurable size (`skipped: "size"`), and time spent is recorded per
    document.
- **Storage:**
  - `reads.jsonl` in the run store, one line per call:
    `{doc, call, agent, node, ts, basis, ranges, request_chars, matched_chars, doc_chars, skipped?}`.
    It holds no text.
  - The working text goes to `doc_texts/<doc>.txt`.
  - Both are new files, so no existing reader of `nodes.jsonl` or `items.jsonl` sees a new record
    shape.
- **Remote Modal jobs:**
  - `reads.jsonl` and `doc_texts/` are added to the remote upload/pull lists (`job/remote.py:203-204`,
    `:413`), so remote runs record them once the worker is next deployed.
  - Until then a remote run shows "not recorded".
  - The redeploy is a paid, live step this work does not take, and remote behaviour stays unverified.
    Local and OpenRouter runs are covered. *(My call, given that OpenRouter is the primary path.)*
- **Switch:** on by default for pipeline runs; the spec knob `job.trace_reads: false` turns it off.
  The knob is documented for future runs. No resume shims are needed, since no run is open.

### Digest (`reports/dashboard/build_floor_digest.py`)

- It reads `reads.jsonl` when present and attaches numbers only, per document: `debug.reads` (agent,
  node, basis, ranges, coverage per call) and the per-agent union.
- Rows from older runs show "not recorded for this run".
- The digest's field notes stay as they are (disagreements only, capped and shortened).

### Viewer (`floor.template.html` and the floor server)

- **Document endpoint:** one new GET route on the loopback floor server takes a run and a doc id and
  returns:
  - the working text (`doc_texts/<doc>.txt`), plus the original row text from `dataset.jsonl`;
  - the row's expected fields and the item's `extracted_data` (`items.jsonl`), so **every** field gets
    a row with full values.

  The server receives the run-store root (today it only knows the digest directory). The route serves
  only those files for a known run and doc id, and keeps the loopback bind. With file://, imported
  digests or no server, the inspector shows the range map without text and says why.
- **DOCUMENT panel** in DEBUG, for the selected document:
  - the working text in a scrollable pane, with a minimap of ranges;
  - one toggle per agent: intake, sorter, reviewer, specialist(s), judge, arbiter, classification
    arbiter, decision lanes;
  - a per-call toggle when an agent ran more than once (retries, resumed documents);
  - band colours taken from the repo's figure colour roles.
- **Field rows:**
  - Expected and extracted value per field. Occurrences are found with whitespace- and
    case-insensitive search in the working text; clicking a field scrolls to them.
  - Flags:
    - **not read:** the expected value occurs in the working text, but in no range read by a specialist
      that ran for this document. All of that specialist's calls count, retries included.
    - **misrouted:** the document's true class's specialist never ran, so no field was extracted for
      that class. This replaces "not read" in that case.
    - **not in text:** the expected value does not occur in the working text at all, for example after
      a label or OCR difference.
- **Accessibility:** keyboard reachable. The open #411 finding (Enter/Space on confusion cells) is
  fixed in passing.

## Constraints

- Offline only: nothing paid or live is needed to build or test this.
- `vendor/` and `vendor_hotfixes.py` are untouched, so `check_hotfixes.py` is unchanged.
- Old run stores keep working.

## Verification (what "done" means)

1. **Matcher red/green tests on synthetic text:**
   - exact ranges for `sliding_windows` windows;
   - exact per-paragraph ranges for `_split_chunks` chunks, including blank-only paragraphs;
   - partial coverage and `basis: raw` before intake;
   - the size skip.
2. **Invariance:**
   - A pytest harness runs mock pipeline documents through `eval/runners.py` with a node sink,
     including a long synthetic document that triggers windowing.
   - Run once with recording on and once off.
   - `items.jsonl` and `nodes.jsonl` match with wall-clock fields stripped. The only exception is the
     intended `classification_arbiter` visits, which are asserted separately.
3. **Failure safety:** a matcher that raises leaves the document's result unchanged.
4. **Privacy:** a test asserts that `floor_digest.json`/`.js` and the export contain no working-text or
   `doc_text` substring longer than a short threshold, and that `reads.jsonl` holds no text.
5. **Viewer:**
   - floor selftest cases;
   - Playwright screenshots (deviceScaleFactor 2) on a synthetic fixture with text, of a
     window-miss field ("not read") and a read-but-missed field.
   - The committed replay fixtures carry no text, and no corpus text is committed.
6. **Repo gates:**
   - ruff;
   - `check_hotfixes.py`;
   - `build_hub.py --check`;
   - CLI surface;
   - runbook;
   - the floor, runner, node-trace, decision-backend and sampling test files;
   - hosted CircleCI green on the PR head.

## Left to the builder

- Shingle length and stride, the caps, the intake state key, and where the writers sit (next to the
  `nodes.jsonl` writer).
- The band palette within the figure colour roles, and the panel layout inside the DEBUG tab.
