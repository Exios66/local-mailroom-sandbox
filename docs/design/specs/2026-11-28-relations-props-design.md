# Relations props: synthetic needle documents for the matter relations clerk

Status: design, awaiting approval (2026-11-28).

## Intent

Smoke tests and proof-of-concept runs need a reliable way to show the matter relations
clerk (`vendor/llm-mailroom/src/pipeline/relations.py`, HUB-040) at work. Today a draw
contains links only by chance: 23 correspondence rows carry `related_document_ids`, so
a 25-document smoke slice usually has no pair the clerk is meant to find.

**Props** are a curated, versioned set of synthetic documents built as **needles**:
follow-up and reminder letters, notices and cover letters that refer back to a specific
document, and attachments (schedules, inventories, exhibits) that a claim or letter
mentions. A run can include them, and a checker then reports which needles the clerk
found, how, and which decoys it correctly ignored.

The set has to be easy to maintain, extend and refine as the clerk improves, and it
ships as its own configs in the next official Hub release of `mailroom-dataset` (v10).

## Goals

- Two kinds of prop, both first-class:
  - **Anchored props** point at real documents already in the Hub corpus, for example
    a reminder chasing a specific Hub insurance claim.
  - **Self-contained clusters** are fully synthetic matters (a claim, its acknowledgment,
    reminder, attachment and demand), always complete even in a tiny smoke run.
- The same document taxonomy and link format as the corpus: `expected_doc_class`,
  `expected_subclass` from the closed vocabulary, the union `gt_fields` schema and the
  existing link fields `matter_id`, `group_id`, `thread_size`, `related_document_ids`
  and `relationships`, matching the 23 linked correspondence rows.
- One spec file per prop (or per cluster member) is the single source of truth, with a
  hand-written body committed beside it. A check fails if a required shared detail is
  missing from the text.
- An offline needle checker that scores each run: recall on positive needles by kind
  and difficulty, and false links on negative needles (decoys).
- Opt-in per run. A run that doesn't ask for props draws, locks and scores exactly as
  it does today.
- Ready for v10 as separate configs, with no change to existing configs, rows or labels.

## Non-goals

- Changing the clerk, its relation vocabulary or its thresholds. The clerk has no
  "follow-up of", "attachment to" or "references" type, and its LLM pass is off
  (`relations.llm: false`). Props record the *intended* relation so they're ready when
  `llm-mailroom` adds one, but that work lives upstream (see "Upstream follow-up").
- Training data. Props are evaluation fixtures, not a training augmentation.
- Generating text with an LLM at build time: no spend and no non-determinism.
- Carrying props through the staged label overlay (`staged_overlay: 9.3.1-rc.N`). The
  overlay is a per-document label delta on existing Hub rows and cannot add rows.

## Anti-goals (failure even if it technically works)

- **Silent score shifts.** Props must never enter headline per-class classification or
  extraction metrics, the experiment log's existing aggregates or the reports hub unless
  asked for. Hand-authored props mixed into correspondence metrics would be a silent
  wrong score (`docs/critical-regressions.md`).
- **Touching real rows.** No back-links: real Hub rows stay byte-identical in v10,
  labels included. The link lives only on the prop. The checker treats links as
  undirected, so detection is scored the same.
- **Train/test leakage.** `experiment_splits.py` merges every document linked by
  `related_document_ids` into one leak component. A prop that joined a train anchor to a
  test anchor would pull them into one group and change the leak audit.
- **Words put in real people's mouths.** The corpus includes real email (the Enron
  correspondence) and real filings. A prop may quote identifiers from its anchor (claim
  and policy numbers, company names, dates, invoice and section numbers, subject lines),
  but it is always written by a fictional sender and never fabricates a statement,
  signature or reply from a real, identifiable person.
- **Coincidence passing as a needle.** A prop that links only because of boilerplate
  (a common insurer name, "Dear Sir or Madam") teaches nothing. Every positive needle
  names the specific details that should carry the link.

## Constraints

- Python 3.11, repo conventions: code under `src/mailroom_sandbox/`, scripts under
  `scripts/`, tests under `tests/`, `ruff`, coverage floor 84.
- Network-free in CI. CircleCI cannot reach the Hub, so anything that reads anchor text
  runs locally against the pinned Hub cache (`HF_HUB_OFFLINE=1` + `HF_HUB_CACHE`, as the
  label-repaired release builder does). CI verifies the committed build.
- No `vendor/` edits. The checker reads the clerk's existing outputs.
- Anchors are pinned to Hub v9.3 (`ff4ca546`, data `7fd99b40`), whose rows and text are
  unchanged since v9.1.
- Document ids follow the corpus format, `DOC-` + 16 lowercase hex.

## Approaches considered

1. **Spec per prop, hand-written body, generated rows (chosen).** A YAML spec states
   what the prop is, what it points at and which details it must share; the body is
   hand-written and committed; one builder emits rows and needles; one checker scores
   runs. Adding a prop is one directory; details can't drift from the text; anchor
   changes are caught by hash. Cost: the most code up front.
2. **Hand-written text plus a manifest row**, like `data/fixtures/manifest.csv`. The
   fastest start, but shared details live in two places and drift, and nothing notices
   when an anchor changes. Rejected for maintainability.
3. **LLM-drafted text at build time.** It costs money on every build and isn't
   reproducible; once frozen, it becomes approach 2. Rejected.

Template-filled bodies were considered within approach 1 and rejected: they read
stiffly and make the needles too easy. Bodies are hand-written.

## Design

### 1. Layout

```
data/props/
  README.md                     how to add, edit and retire a prop; changelog
  props.yaml                    set name, set version, schema version, defaults
  anchored/
    <prop_id>/
      prop.yaml                 the spec
      body.txt                  the document text, hand-written
  clusters/
    <cluster_id>/
      cluster.yaml              the shared world: matter, parties, numbers, dates, split
      <member_id>.yaml          one spec per member (same schema as prop.yaml)
      <member_id>.txt           its body
  build/<version>/              generated, committed, verified by --check
    props_default.jsonl         filename, id, doc_text, content_sha256
    props_ground_truth.jsonl    labels and link fields, keyed by filename
    props_needles.jsonl         one row per expected (or forbidden) link
    anchor_ids.txt              Hub document ids the set anchors to
    MANIFEST.json               set version, schema version, file sha256s
```

### 2. Spec schema

```yaml
prop_id: auto-claim-second-request          # stable slug; never reused once released
doc_class: correspondence
subclass: letter                            # closed vocabulary (taxonomy)
intended_relation: reminder_of              # props vocabulary, see below
difficulty: medium                          # easy | medium | hard
polarity: positive                          # positive | negative (a decoy)
split: inherit                              # anchored: inherit; cluster: in cluster.yaml
anchors:
  - hub:                                    # a real corpus row
      filename: "auto:123456789.txt"
      document_id: DOC-0123456789abcdef
      content_sha256: "<64 hex>"
    expected_signals: [party_overlap, topic_overlap]   # clerk relation types
    hooks:                                  # must appear verbatim in body.txt;
      claim_number: "CLM-2024-118843"       # for a hub anchor, also in the anchor text
      parties: ["Ridgeway Mutual Insurance"]
      dates: ["March 4, 2024"]
      phrases: ["second request"]
  # or, inside a cluster:
  # - member: claim-notice
gt_fields: {...}                            # union schema: sender, recipient,
                                            # communication_date, intent, keywords, ...
notes: why this needle exists and what it tests
```

- **Intended relations (props vocabulary, closed):** `follow_up_of`, `reminder_of`,
  `reply_to`, `attachment_of`, `references`, `cover_letter_for`, `supersedes`, and
  `unrelated` for decoys. They are stored in the props files, never mapped onto the
  clerk's types.
- **Expected signals** use the clerk's types (`topic_overlap`, `party_overlap`,
  `semantic_similarity`, `temporal_proximity`, `llm_asserted`). They say how the clerk
  *can* find the link today, so a miss is diagnosable. `same_matter` is refused: the
  sandbox ingests every row under its own run-scoped catalog matter
  (`sandbox_matter_id`, `src/mailroom_sandbox/eval/runners.py:40`), and props keep that,
  so needles must be found from content alone. The derived `matter_id` / `group_id` are
  ground truth only and are never passed to the pipeline (designer's call).
- **Negative props (decoys)** share surface details with an anchor (same insurer, a
  nearby date, the same form letter) but belong to a different matter (a different
  claim or policy number). Polarity `negative`: the expected result is *no* edge. The
  clerk's own prompt says "coincidence is worse than silence"; decoys measure it.

### 3. Derived fields (the builder writes them, never the author)

- `id` / `document_id`: `DOC-` + the first 16 hex of `sha256("relations-props:" + prop_id)`.
  It's derived from the slug, not the text, so editing a body doesn't change the id.
- `filename`: `props/<cluster_id or anchored>/<prop_id>.txt`, unique and obviously
  synthetic.
- `content_sha256`: of the body, as the corpus defines it.
- `matter_id`, `group_id`: a cluster uses `MATTER-PROP-<cluster_id>` /
  `GROUP-PROP-<cluster_id>`. An anchored prop reuses its anchor's `matter_id` and
  `group_id` when the anchor has them, and otherwise uses `MATTER-PROP-<prop_id>`.
  Decoys always get their own matter.
- `thread_size`: members of the group present in the set (a cluster's size; for an
  anchored prop, 1 + its anchors).
- `related_document_ids`: the anchors' Hub ids plus cluster siblings it links to,
  sorted. Decoys carry none.
- `relationships`: mirrors the Hub format exactly (see "Left to the builder").
- `split`: an anchored prop inherits its anchors' split. A cluster declares one.
- `source_corpus: relations_props`, `annotation_method: synthetic_authored`,
  `expected_specialist` / `expected_stage` as the corpus derives them for that class.

### 4. Checks (`scripts/build_relations_props.py`)

`--check` (network-free, runs in CI's `checks` job like `build_hub.py --check`):

- Every spec validates: closed class, subclass, intended relation, signal and difficulty
  vocabularies; unique `prop_id`s; anchors resolve (a cluster member exists; a hub anchor
  has a filename, id and 64-hex hash).
- Every hook appears verbatim in its body (whitespace-normalized, case-sensitive).
- No anchored prop has anchors in both splits; a cluster has one split.
- Derived ids don't collide inside the set; `anchor_ids.txt` matches the specs.
- A decoy has no `related_document_ids` and shares no `matter_id` with its look-alike.
- Rebuilding from the specs reproduces `build/` byte for byte.

`--verify-anchors` (local, needs the pinned Hub cache, also part of the release step):

- Each hub anchor's filename, id and `content_sha256` match the pinned revision.
- Each hub-anchor hook also appears in the anchor's text, so the needle really is shared.
- No derived prop id collides with a Hub id.

### 5. Using props in a run

A new opt-in field next to `staged_overlay`:

```yaml
dataset:
  name: family-corpus
  staged_overlay: 9.3.1-rc.10      # unchanged; applies to Hub rows only
  props: relations-props@1.0       # pinned in the committed MANIFEST.json
```

- **Ride-along selection.** The draw happens exactly as today. Then the run appends
  every cluster member and every anchored prop whose anchors are *all* in the drawn
  set. The lock records the props version, the MANIFEST sha256, the included prop ids
  and each skipped anchored prop with its reason ("anchor not in draw").
- **Anchors-first smoke.** For a run that should hit every anchored needle, a committed
  smoke config draws exactly `anchor_ids.txt`. No include-by-id draw exists today
  (`DatasetSpec` has only `exclude_ids_file`), so this adds `dataset.include_ids_file`,
  hashed only when set, like `interim_labels`.
- **Hashing.** `props` enters the request hash only when set (the `interim_labels`
  pattern), so existing locks and their hashes don't change.
- **Scoring separation.** Prop rows are classified and extracted like any other document,
  but their results go to their own `props` bucket. By default they are excluded from
  per-class and aggregate metrics, the experiment log's aggregates and the reports hub.
  A report may show the props bucket next to them, labeled as such.
- **Mock mode.** `sandbox pilot --mock` takes no `DatasetSpec` (it runs the fixture
  manifest), so it gets its own `--props <version>` flag that appends the cluster
  members to the fixture rows. Party and keyword signals then depend on mock extraction,
  so the checker reports which signals were even possible (see below) instead of
  calling them misses.

### 6. The needle checker

`sandbox props check --run <run_dir>` (offline, read-only, no LLM):

- Opens the run's `mailroom/mailroom.db` and reads `relation_edges` after
  `settle_mailroom_writers()` has finished.
- Maps pipeline document ids to dataset ids through the run's document catalog
  (`original_filename`, with `content_sha256` as the fallback).
- For each needle in `props_needles.jsonl` that the run included:
  - **positive:** found or missed (any edge, either direction); the clerk relation types
    and max score on the found edge, against `expected_signals`.
  - **negative:** clean, or a false link (any edge between the decoy and its look-alike).
  - **possible signals:** whether the extraction gave the clerk the fields a signal needs
    (keywords, party fields, a date) and whether embeddings were available, so
    "not possible in this run" is kept apart from "missed".
- Writes `reports/props_check.json` and `props_check.md` in the run directory:
  recall overall, by intended relation, by difficulty and by kind (anchored vs cluster);
  the decoy false-link rate; and one row per needle.
- `--rescan` (optional): copies the database and runs the vendored offline full rescan
  (`pipeline.relations_scan --full`, deterministic, no LLM) before checking. That removes
  archive-order effects (a prop scanned before its anchor was archived).

### 7. Seed set (v1.0)

About 16 props, a difficulty ladder across both kinds. The exact anchors are picked in
the plan from the pinned corpus by the anchor rules (identifiers present, one split,
no real person's voice needed).

Anchored (real Hub rows):

- A **second-request reminder** chasing a Hub auto claim for missing documents (claim
  number, policy number, insured party). Easy.
- An **adjuster follow-up** on a Hub property claim, citing its date of loss and the
  damages description. Medium.
- An **attachment**: "Schedule A – itemized damages" that a Hub claim's
  `supporting_documents` describes; sparse tabular text, linked only by claim number and
  amounts. Hard.
- A **notice of non-renewal** under a Hub CUAD agreement, naming the agreement, parties
  and its notice section. Medium.
- A **cover letter transmitting** a Hub officer certificate or board resolution, naming
  the entity, the resolution date and the certified matter. Medium.
- A **follow-up to a Hub demand letter** from opposing counsel's (fictional) firm,
  quoting the subject line and amount. Medium.
- **Decoys:** a reminder from the same insurer about a different claim number in the
  same month, and a form notice with matching boilerplate but no shared identifiers.

Clusters (fully synthetic):

- **"Bridgeway flood"**: a property claim, the carrier's acknowledgment, a 30-day status
  reminder, an exhibit (damage inventory with photos listed), a coverage-position letter
  and counsel's demand. It tests chains and temporal proximity.
- **"Northwind / HarborPoint MSA"**: extends the existing fixture world without copying
  it. The cluster has its own earlier first-notice letter (a new text, never a byte copy
  of `data/fixtures/correspondence/sample_demand_letter.txt`, so no two documents share
  a `content_sha256`), then HarborPoint's response, a payment-plan memo quoting invoices
  100241, 100287 and 100341, and a final notice of termination. In a `--mock` pilot the
  fixture demand letter is also present and will likely link to the cluster. The
  checker lists such edges as "incidental" and doesn't score them.
- **"Quiet attachment"**: a two-line transmittal email plus an attached invoice ledger
  that shares only invoice numbers and a party name, and a decoy ledger from a different
  vendor. It is the hardest needle in the set.

### 8. Versioning and maintenance

- The set version lives in `props.yaml`: adding props or editing a body is a minor bump
  (`1.0` → `1.1`); removing a prop or changing an anchor is a major bump. A `prop_id` is
  never reused. The README changelog records every bump.
- Each released version keeps its own build directory, `data/props/build/<version>/`,
  and `config/props.yaml` pins every version to its MANIFEST sha256, mirroring
  `config/staged_overlays.yaml`. Run locks pin the version and sha256; a mismatch
  refuses to run. Runs always read the committed build, before and after v10; the Hub
  configs are a publication of it, not a second source (designer's call).
- Adding a prop: create a directory, write the spec and body, run
  `build_relations_props.py`, run `--verify-anchors` if it anchors to Hub rows, commit
  the spec, body and rebuilt `build/`. CI's `--check` refuses anything else.
- A docs page (`docs/relations-props.md`) explains authoring rules, including the
  real-person rule and the decoy recipe, and is indexed in `docs/README.md`.

### 9. Release (v10)

- Three new configs in the Hub repo: `props_default` and `props_ground_truth` (same
  split names, the same shapes as `default` / `ground_truth`), and `props_needles`.
  Existing configs, their rows and their labels are unchanged.
- The dataset card gains a "Relations props" section: what they are, that they are
  synthetic, how to opt in and how to score needles, and that they're excluded from
  headline metrics.
- The release step runs `--check` and `--verify-anchors`, converts `build/` to parquet
  and records the props version in the card's versions table.
- The props are not added to the staged overlay; the overlay stays as cut.

### 10. Upstream follow-up (not in this change)

File an `llm-mailroom` issue proposing reference-aware relations (explicit identifier
matching such as claim, policy and invoice numbers, and `follow_up` / `attachment`
relation types). The props' `intended_relation` labels are the ready-made evaluation set
for it.

## Testing

- Unit tests for spec validation (each rule, including the split and decoy rules), id
  derivation, deterministic rebuild, ride-along selection and its lock record, the
  request-hash rule (unchanged when `props` is unset) and metric separation.
- Checker tests against a small SQLite fixture with hand-made `relation_edges` and
  catalog rows: found, missed, false link, not-possible signal, direction-agnostic match.
- `build_relations_props.py --check` added to CircleCI's `checks` job.
- A `sandbox pilot --mock` smoke that includes the Northwind / HarborPoint cluster and
  produces `props_check.md`.

## Decided in conversation

- Approach 1 (spec per prop, hand-written body, generated rows and needles, a checker).
- Both anchored props (real Hub rows) and self-contained synthetic clusters.
- The existing link fields and format (`related_document_ids` and friends), like the
  linked correspondence rows.
- No back-links on real rows; the checker treats links as undirected.
- v10 is already in preparation; interim and near-gold labels stay on the staged overlay
  for experimental scoring, and props stay out of it.

## Calls made by the designer (open to correction)

- Separate configs for v10 rather than new rows in `default` / `ground_truth`.
- Opt-in `dataset.props` with ride-along selection; draws unchanged.
- Props excluded from headline metrics by default.
- Decoys (negative needles) in the set.
- The real-person rule for anchored props.
- Ids derived from `prop_id`, not text; the `MATTER-PROP-` / `GROUP-PROP-` prefixes.
- `annotation_method: synthetic_authored`, `source_corpus: relations_props`.
- The seed set's shape and size (about 16).

## Left to the builder

- The exact `relationships` value format: read it from the 14 Hub rows that carry it and
  mirror it; if it can't hold an intended relation, keep that only in `props_needles`.
- Whether the `annotation_method` vocabulary is closed anywhere (dojo schemas, label EDA,
  release builder) and needs `synthetic_authored` registered.
- How the pipeline document id maps to the catalog in a run directory, confirmed against
  a real `--mock` run.
- CLI wiring (`sandbox props build|check`) versus script-only, and the module layout.
- Which existing reports or aggregators need an explicit props exclusion.
