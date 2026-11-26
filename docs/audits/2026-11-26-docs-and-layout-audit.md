# Docs and repository layout audit (2026-11-26)

This audit checks whether the docs and the repository layout are still up to date and easy to follow,
after many hotfixes and features have landed since the entry docs were written. It records what
was checked, what was found, and a phased plan to fix it. Nothing outside this file was changed.

- **Checkout:** `claude/practical-darwin-2ucd2f` at `e344b0b` (shallow clone, about 73 commits; dates
  from `git log` cluster on the graft commit, so file age was not used as evidence).
- **Method:** the [docs-audit tool router](../../.cursor/skills/docs-audit-tool-router/SKILL.md) full
  sweep, plus three read-only audits (entry docs against code, the `docs/` tree, repository
  tidiness). Findings below were checked against the files they cite.
- **Not checked:** external facts (releases, prices, model availability), hosted CI results, and
  whether each superseded run config was ever launched.

## Summary

The mechanical checks pass. Links resolve, the generated files are current, and the hotfix
registries match their docs. What is wrong is what those checks cannot see:

1. **The entry docs disagree with the code in a few places**, and they say nothing about hotfixes.
   README has no mention of hotfixes at all.
2. **Most docs cannot be found by navigation.** README never links `docs/README.md`, which indexes
   16 links for 35 root docs. 41 docs cannot be reached from either README, and 34 have no inbound
   link at all.
3. **Entry docs have absorbed history.** Run IDs, per-class rates, upstream PR lists and full command
   specs sit in README and `AGENTS.md`, where they make the guidance hard to find.
4. **`docs/` and `scripts/` have no structure for finished work.** Experiment designs, point-in-time
   reviews and live guides share one directory. 14 scripts have no reference, and two duplicate
   `sandbox` subcommands.
5. **Nothing stops this from happening again.** No test checks that a doc is indexed, that a hotfix
   ID is documented, or that the README layout matches the tree.

## Mechanical checks (all passed)

| Check | Result |
| --- | --- |
| `pytest -q tests/test_doc_paths.py -n 0 --no-cov` | 3 passed |
| `python scripts/check_cli_surface.py --check` | CLI reference is current |
| `python scripts/sync_requirements.py --check` | all `ok` |
| `python reports/dashboard/build_hub.py --check` | ok: 1,844 figures, 781 cross-checks |
| `sandbox runbook check` | OK (pins + generated docs) |
| `sandbox subagents doctor --no-global` | 0 fail, 1 warn (Node 22 < 24 for eve, local only) |
| `sandbox subagents sync --harness project --check` | clean |
| `npx --yes markdownlint-cli2@0.18.1` | 0 errors in 203 files (globs skip `reports/`, `data/`, `docs/prompts/`) |
| `git diff --check` | clean |

Checked and consistent across docs and code:

- the vendor pins `8cebcd8` / `7d69bbd` (`_VENDOR_PINS`, both `VENDOR.md`, README badges,
  `requirements/dojo-release.txt`)
- the coverage floor of 84
- the model ids
- the 13-node graph
- `modal==1.6.4`
- HF-001..017 and SHF-001..016, including SHF-014 marked retired

## Findings

### A. Entry docs that are wrong (verified)

| # | Where | Claim | Evidence | Fix in |
| --- | --- | --- | --- | --- |
| A1 | `README.md:103` | Example `sandbox deps fetch --component dojo --version v0.29.0` | [`dependency-snapshots.md`](../dependency-snapshots.md) lines 67-71: a Dojo release before llm-dojo-scoring #185 (v0.30.1 included) is never selected | README; the guide's own `v0.28.1` examples |
| A2 | `AGENTS.md:19`, `:309` | "no pip git pins", scoring "pinned by the tracked snapshots" | `requirements/dojo-release.txt` is a git pin and calls itself the primary scoring source; `dojo_source.py` `auto` order is installed release, then cache, then `vendor/` | One source-precedence paragraph in AGENTS, mirrored in README:58-62 |
| A3 | `AGENTS.md:248` | Backends `local`/`api`/`jev`/`mock`, example `api:openai/gpt-6-luna` | `decision_backends.py:1644` accepts `decisions`, the recommended backend; the next bullet calls chat-model Luna runs a mistake | AGENTS |
| A4 | `AGENTS.md:32` | "The historical sandbox v0.2.0 release exists" | `pyproject.toml` is `0.3.0`; CHANGELOG has `[0.3.0] - 2026-10-17` | AGENTS |
| A5 | `CLAUDE.md:59-61` | CircleCI job list | Omits `notebook-regressions` (`.circleci/config.yml:176`, `:221`) | CLAUDE |
| A6 | `CLAUDE.md:87`, `AGENTS.md:245`, `LAYOUT.md:25,109` | `reports/experiment_log.jsonl` presented as a standing file | Gitignored (`.gitignore:47`); written only at runtime | Say "runtime-generated" |
| A7 | `config/models.yaml:3` | Cites `docs/openrouter-sunset-audit.md` | Now [`docs/archive/openrouter-sunset-audit.md`](../archive/openrouter-sunset-audit.md) | `config/models.yaml` comment |
| A8 | `config/mailroom.taxonomy.base.yaml:257` | Cites `docs/reports/audits/PILOT_AUDIT_REPORT.md` | No such file or directory | Taxonomy comment (find or drop the citation) |
| A9 | docs-audit router `SKILL.md:37,88,89`; `governance/TASKS.md` | Hands work to `archivist-file-organizer` and `atom` | Neither exists in `.opencode/agents/`, `.cursor/agents/`, `.claude/agents/` or `config/subagents/`; `docker-deployment-specialist`, `ml-systems-oracle` and `lucius` also only appear in governance | Router skill and TASKS.md: name a real owner or "maintainer" |
| A10 | `CLAUDE.md:82-84` vs `AGENTS.md:242` | Flags `sandbox autoresearch` refuses | CLAUDE lists three, AGENTS four (adds `--agent-model`); check the parser | Whichever is wrong |

Suspected but not verified:

- README FAQ (`:424`, `:449-452`) says vendor snapshots move when the Digital-Mailroom hub
  regenerates them. Both `VENDOR.md` files say the last refresh used standalone `sandbox fetch-deps`.
- "Langfuse SDK v4" (README:13, AGENTS:251) is narrower than `langfuse>=4.0,<6`.
- `AGENTS.md:165` cites a personal path (`~/Downloads/...`).

### B. Coverage gaps (features and patches the entry docs never mention)

- **Hotfixes have no onboarding.** README never mentions them. AGENTS has one clause (`:309`), and
  CLAUDE covers vendor hotfixes only. [`scoring-hotfixes.md`](../scoring-hotfixes.md) is linked from
  none of README, AGENTS, CLAUDE, `docs/README.md` or QUICKSTART. The hotfix docs themselves are
  accurate. What's missing is a way in to them.
- **Commands no entry doc mentions:**
  - top-level: `circleci`, `modal-matrix`, `modernbert`, `pain-points`, `review`, `schemas`,
    `scorecard`, `splits`
  - `run` subcommands: `benchmark-check`, `card`, `deploy-env`, `dispose`, `export-bt`, `routing`,
    `scrape-metrics`, `suite`
  - `metrics` subcommands: `estimate-suite`, `extrapolate`, `serving-record`
  - others: `traces pack`, `subagents packages`

  The worst gap is `sandbox review list|show|resolve`: AGENTS explains how documents park for human
  review but not how to resolve them.
- **Recent work reachable only through unlinked pages:**
  - the scored n beside the extraction headline (#421)
  - #214 confidence windows (#396-#402)
  - staged overlay rc.10 (#422)
  - stale-Hub-label drop (#418, SHF-015)
  - OpenRouter routing bounds (#410)
  - intake and arbiter OpenRouter fixes (#417, #420)
  - pain-point composites
  - the `pipeline` compose profile
- **Layout maps are stale.**
  - README:350-367 omits `scripts/`, `tests/`, `requirements/`, `research_notes/`, `data/labels/`,
    `data/handoff/` and seven `config/` subdirectories.
  - `docs/setting-up/LAYOUT.md:26` says only `fixtures/` is tracked under `data/`.
  - [`reports/README.md`](../../reports/README.md) describes 5 of its 22 subtrees.
  - [`scripts/README.md`](../../scripts/README.md) describes 1 of 75 scripts.

### C. Navigation (the `docs/` tree)

- 142 tracked docs under `docs/`, `governance/`, `research_notes/` and `api-evals/`.
- 34 docs have no inbound link, and 18 of those are never mentioned anywhere. Among them:
  `SAND42-ISSUE-UPDATES.md`, `rb1-evaluation-design-v2.md`, three `audits/`, both `releases/`, and
  `governance/subagents/README.md`.
- 41 docs cannot be reached from README or `docs/README.md`, including all of `superpowers/`, half of
  `audits/`, `roadmaps/`, `datasets/`, `gold-labels/` and eight root design docs.
- `docs/README.md` still has placeholder bullets and one mislabelled link (`benchmark-l4.md` points
  into `modal/`).
- The CLI is described four times: README Quickstart, SANDBOX-GUIDE §5 (659 lines),
  `setting-up/QUICKSTART.md` and the generated `cli-reference.md`. The four agree today; only the
  generated one is checked.
- Naming is mixed: 26 UPPERCASE, 86 kebab-case, 10 snake_case and 19 date-prefixed files. A ticket
  is spelled `SAND42-`, `sand42/`, `SAND-042` and `sand214` in different places. The only paths
  with spaces are `research_notes/Modal vLLM measurement priorities/` and
  `reports/Modal vLLM measurement priorities.md`, and they hold 14 files between them.
- `research_notes/.../hotfixes.md` is a stale snapshot: it lists 8 HFs at `fedda378`, where there
  are now 17.

### D. Readability (history living in entry docs)

| Where | What | Move to |
| --- | --- | --- |
| `AGENTS.md:249` (1,945 chars) | Luna calibration run IDs, per-class rates, superseded configs, resume semantics | `reports/reviewer-calibration/`, [`decision-model-inputs.md`](../decision-model-inputs.md) |
| `AGENTS.md:234` (1,186 chars) | Full `sandbox floor` spec inside the command block | [`floor.md`](../floor.md) |
| `AGENTS.md:220,242,247,248,250,309` | Policy mixed with SAND-085/086/089 history | Keep the rule, link the history |
| `AGENTS.md:258-300` | Repeats README extraction rules plus HUB-015 history | One owner, one link |
| `README.md:377-396` | Generated table of pins and upstream PR numbers (lines up to 774 chars), then an unrelated API-token paragraph inside "Layout" | `VENDOR.md` already holds the pins; move the token paragraph to Safety |
| `README.md:540-554` | "DMR-111" section after the footer, with CUAD scoring notes | [`dependency-snapshots.md`](../dependency-snapshots.md), [`evals.md`](../evals.md) |
| `README.md:49`, `:330-341` | Stray line before the first heading; "Extraction gate" nested under extraction rules | Restructure |
| `CLAUDE.md:33-39` vs `AGENTS.md:86-96` | Near-verbatim duplicate of dependency-source rules | CLAUDE keeps the rule, links AGENTS |
| `CHANGELOG.md:5-1291` | ~1,290-line `[Unreleased]`, no release since 0.3.0 | Cut a release (maintainer decision) |

### E. Repository tidiness

| # | Finding | Evidence | Action class |
| --- | --- | --- | --- |
| E1 | Top-level `autoresearch/` is a leftover orchestrator handoff (2 JSON files) | Unreferenced; real output is `reports/autoresearch/`, configs `config/autoresearch/` | Safe now: delete |
| E2 | `scripts/sync_subagents.py`, `scripts/propagate_family_subagents.py` duplicate `sandbox subagents sync`/`propagate` | Unreferenced; same functions (`cli.py:2273`, `:2343`) | Safe now: delete |
| E3 | `.gitignore` lists `data/archive` and `data/warehouse` twice | Lines 22-23 and 142-143 | Safe now |
| E4 | 14 unreferenced scripts in `scripts/sand032/` and `scripts/sand42/` (`flow2-5.sh`, `rerun-*.sh`, `smoke-metrics-gate.sh`, `campaign-*.sh`); most contain `modal deploy`/`run start` | Script reference scan | Decision: archive to `scripts/archive/<ticket>/` or delete |
| E5 | Nine chat-model Luna run configs AGENTS calls superseded sit in `config/runs/` | Only `reviewer-calibration-luna.yaml` is linked (2 docs); `config/runs/legacy/` already exists | Needs reference updates: move to `legacy/` |
| E6 | `research_notes/` (13 files, spaces in path) and the loose report cover the same subject | Unreferenced by code/tests; 7 relative links checked by `test_doc_paths` | Needs reference updates: `docs/research/modal-vllm-measurement-priorities/` |
| E7 | 17.4 MB of release CSVs in `reports/datasets/mailroom-dataset-v9.3-label-repaired/` | No code or test reads them; README calls them an HF dataset release | Decision: publish on HF and keep README + builder, or keep and stop adding |
| E8 | `.claude/agents/` wrappers are hand-written and untested | `sandbox subagents sync` has no `claude` harness | Optional: small test that each wrapper's target exists |
| E9 | `build_decisions_report.py --check`, `sand032/rerender.py --check`, `export_hub_reports.py --check` exist but are not in CI | `.circleci/config.yml` | Decision: add to the `checks` job |

Do **not** move or rename (code and tests depend on them):

- Ticket report folders `SAND42`, `SAND-37` and `SAND-32`, and `reports/YYYY-MM-DD/`. These are
  used by `report_paths.py:133`, `job/grid_cards.py:46,52`, `dashboard/hub_extract.py:192-208`,
  `test_dated_reports.py` and `job/dated_reports.py`. Document the convention instead.
- `config/runs/rb1-*` and `sand42-*`. Tests and `job/sand42_cards.py` glob them non-recursively.
- `docs/runbooks/` (`GENERATED_REL` in `job/runbooks.py`) and `docs/prompts/` (byte-compared by tests).
- Large `data/labels/**` and `data/handoff/**` JSONL files are read by code and tests. Keep them in
  git: LFS would break the network-free suite.

## Plan

Six PR-sized phases, ordered by value per risk. Phases 1-3 are docs-only and can land without a
maintainer decision. Phases 4-5 move files and need the decisions listed at the end. Phase 6 keeps
the tree from drifting again. Each phase re-runs the mechanical checks table and records its audit
boundary in the PR's **Critical regressions** section (docs-only phases: no score, draw, model or
cost path touched).

### Phase 1: correct what is wrong (docs-only, small)

- Fix A1-A10 in their owning files.
- Reconcile the vendor ownership story (hub regeneration vs standalone `fetch-deps`) into one
  statement in AGENTS, then align the README FAQ.
- `.gitignore` duplicates (E3).
- Done when every row in A is fixed or recorded as checked-and-correct, and the mechanical checks
  pass.

### Phase 2: make everything findable (docs-only)

- Rewrite [`docs/README.md`](../README.md) as the single index, grouped into these sections:
  - **Start here:** QUICKSTART, SANDBOX-GUIDE, LAYOUT
  - **How-to:** experiments, evals, rescore, jobs, floor, tracing, autoresearch
  - **Reference:** CLI reference, dependency snapshots, decision-model inputs, pain-point
    composites, staged overlay
  - **Hotfixes:** vendor and scoring
  - **Safety and review:** critical regressions, campaign-preparation regressions, PR review lanes,
    agent dispatch, instruction maintenance
  - **Design records:** one line per ticket
  - **Audits**
  - **Archive**

  Drop the placeholder bullets.
- Link `docs/README.md` from README's Docs section, as its first row.
- Add a short **Hotfixes** section to README and AGENTS. It should say what HF and SHF are, that
  `vendor/` is never patched, where the registries live, and link both docs.
- Extend README's CLI block with the missing commands (B), grouped. Point to `cli-reference.md` for
  flags instead of listing them.
- Update `docs/setting-up/LAYOUT.md` (the owner), then make README "Layout" a short tree linking it.
- Rewrite `reports/README.md` as a table with one row per subtree: what writes it, whether it is
  generated or frozen, and which check guards it. Document the ticket-folder spelling there.
- Rewrite `scripts/README.md` as an index: maintained tools, per-ticket campaign scripts, and the
  ones that spend money.

### Phase 3: slim the entry docs (docs-only)

- Move the D rows into their owning docs and leave one-line links behind.
- Give README a fixed shape:
  1. what it is
  2. when to use it
  3. quickstart
  4. how it works
  5. CLI overview
  6. hotfixes
  7. docs index link
  8. layout
  9. FAQ
  10. contributing

  Remove the DMR-111 tail and the pin table.
- Make CLAUDE.md a pointer file: rules that bite, then links to AGENTS for detail. Remove its
  near-copies of AGENTS sections (dependency sources, CI list), so there is one place to update.
- Make `cli-reference.md` the only CLI walkthrough. SANDBOX-GUIDE §5 becomes a pointer, and QUICKSTART
  covers the first run only.
- Remove the stale `research_notes/.../hotfixes.md` snapshot, or add a banner on it pointing to
  `vendor-hotfixes.md`.

### Phase 4: restructure `docs/` (moves; needs decision 1)

- Keep evergreen how-to and reference docs at the `docs/` root.
- Move experiment designs into `docs/design/<ticket>/`:
  - `sand42/` ← `SAND42-EXPERIMENT-DESIGN`, `SAND42-FOLLOWUP-DESIGN`, `SAND42-SCHEMA-ADHERENCE-RCA`
  - `sand037/` ← `SPECIALIST-GRID-PLAN`
  - `sand043/` ← `BENCHMARK-PROGRAM`, with a historical banner because it cites the old v9.1 pin
  - `dmr068/` ← `scale-matrix`
  - `rb1/` ← `rb1-evaluation-design-v2`, `EXTRACTION_GATE_VETTING`, and the 2026-11-18 runbook plan
  - `sand034/` ← `roadmaps/PROMPT-ENHANCEMENT-PLAN-v2`
- Move the remaining `superpowers/` plans and specs to `docs/design/plans/` and
  `docs/design/specs/`, keeping their date prefixes.
- Move `rb1-r13b-smoke-review` and `sand214-window-learnings` to `docs/audits/` with date prefixes.
- Move to `docs/archive/`: `SAND42-ISSUE-UPDATES`, `roadmaps/prompt-enhancement-plan`, and
  `audits/2026-11-19-hotfix-followup`.
- Move `research_notes/` and the loose report to `docs/research/modal-vllm-measurement-priorities/`
  (E6).
- For every moved file:
  - add its old path to `_STALE_DOC_PATHS` in `tests/test_doc_paths.py`
  - fix the inbound links
  - fix the citations in `config/runbooks/catalog.yaml`, then run `sandbox runbook write`
  - fix the `src/` citations: `gold_audit.py`, `check_g0.py`, and the SAND42 and specialist-grid
    references
- The serving-ladder spec has 32 references outside Markdown. Move it last, or leave it where it is.
- Naming rule going forward: kebab-case for new docs, a date prefix for point-in-time audits and
  plans, and a ticket directory for designs. Existing UPPERCASE root docs that stay are left as they
  are, to avoid churn.

### Phase 5: tidy the tree (moves and deletes; needs decisions 2-4)

- Delete `autoresearch/` (E1) and the two duplicate scripts (E2).
- Archive or delete the 14 unreferenced campaign scripts (E4).
- Move the nine superseded Luna configs to `config/runs/legacy/` and fix their two links (E5). First
  check the run locks to confirm whether the three unreferenced configs were ever launched.
- Large CSVs (E7) and the extra CI gates (E9), as decided.

### Phase 6: keep it from drifting (tests and process)

New network-free tests, each run as a named file with `-n 0 --no-cov`:

- Every tracked `docs/**/*.md` is linked from `docs/README.md`, transitively. Generated runbooks,
  `prompts/` and an explicit allowlist are exempt.
- Every `HF-NNN` and `SHF-NNN` in `vendor_hotfixes.py` / `scoring_hotfixes.py` has a row in its doc,
  with the same active or retired status.
- Every top-level `sandbox` subcommand is named in README's CLI overview. Only the top level, so
  README stays short.
- Every top-level directory is listed in `LAYOUT.md`.
- `docs/...` paths cited in YAML and Python comments resolve. This would have caught A7 and A8.
- Each `.claude/agents/*.md` wrapper points at an existing `.opencode/agents/` file (E8).
- Agent names cited in skills and `governance/` exist in the roster (A9).

Process changes:

- Add "docs touched?" to the PR template next to Critical regressions. A PR that adds a hotfix,
  subcommand or top-level path must update the index row the new tests check.
- Run the docs-audit router sweep before each release cut, and record the result in `docs/audits/`.

## Decisions for the maintainer

1. **`docs/` restructure scope.** Recommended: Phase 4 as written, skipping the serving-ladder spec.
   The alternative is to only index the files (Phase 2) and leave them where they are.
2. **Unreferenced campaign scripts (E4).** Recommended: archive to `scripts/archive/<ticket>/`. They
   are campaign provenance, and shellcheck keeps linting them there.
3. **Release CSVs (E7).** Recommended: publish them on the HF dataset revision and keep only the README
   and builder here. That frees 17 MB; it is irrelevant if repo size is not a concern.
4. **Extra `--check` gates in CI (E9).** Recommended: add all three to the `checks` job.
5. **Ticket folder spelling.** Recommended: keep `SAND42`, `SAND-37` and `SAND-32` and document the
   convention. Renaming touches code, tests, the hub and the catalog for no functional gain.
6. **Release cut.** `[Unreleased]` holds about 1,290 lines since 0.3.0. Cutting 0.4.0 after Phase 3
   would give the docs a stable reference point.

## Outcome (2026-11-26, same branch)

The maintainer chose: keep the release CSVs (E7), do the full `docs/` reorganization
(decision 1), add the extra `--check` gates to CI (E9), and release a new version (decision 6).
Decision 2 had no answer, so the unreferenced campaign scripts were archived, as
recommended, not deleted. Decision 5 (ticket folder spelling) took the recommended
default: kept, and documented in `reports/README.md`.

Where the work differs from the plan above:

- **Two docs stay at the root.** `EXTRACTION_GATE_VETTING.md` and
  `rb1-r13b-smoke-review.md` are cited by `config/decisions/` question sets, which are
  byte-hashed into run locks (`questions_sha256`), and by committed campaign config copies
  under `reports/campaigns/`. Editing those citations would change a frozen identity, so
  both are indexed in place. Run-config comments were safe to edit: `spec_hash` is computed
  from the parsed spec, not the file bytes.
- **The serving-ladder spec moved after all**, with the other superpowers plans and specs: its 31
  run-config citations are comments.
- **`export_hub_reports.py --check` is not in CI.** It compares against a sibling
  `mailroom-issues` checkout. `scripts/sand032/rerender.py --check` crashed on the
  committed tree (its glob reached other generators' figure folders) and was fixed first.
- **The agent-name check is narrower.** The docs-audit router now names real owners. The
  old assignee names in `governance/TASKS.md` are board history and were left as they are.
  `tests/test_docs_drift.py` checks the `.claude/agents` wrappers but not free-text agent
  names.
- **`uv.lock` was stale** against `pyproject.toml` (#403, #404) and was regenerated in its
  own commit before the version bump.
- **No new release was cut.** This audit missed that `v0.3.5` (2026-10-30) and `v0.4.0`
  (2026-11-18) had already been published on GitHub without CHANGELOG sections or a version
  bump; the clone was shallow and had no tags. The CHANGELOG now has a `[0.4.0] - 2026-11-18`
  heading at the tag's boundary, this work stays under `[Unreleased]`, and the package
  version reads 0.4.0 to match the published release. A follow-up added
  `[0.3.5] - 2026-10-30`: all 62 entries of that tag's `[Unreleased]` section sit under it in
  their original order, and the 16 entries filed among them after the tag moved up into 0.4.0.
