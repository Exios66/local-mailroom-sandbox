---
name: docs-audit-tool-router
description: Route a full documentation staleness sweep in local-mailroom-sandbox. Use before a docs/README audit, after command, config, vendor, release or PR-stack changes, when a README claim or reference looks old, or before handoff/merge; it names the mechanical checks, evidence sources, owning files and specialist agents instead of guessing.
---

# Docs audit tool router

Use this when the task is **find and correct stale documentation**, not merely
edit one page. The [instruction maintenance procedure](../../../docs/agent-instruction-maintenance.md)
defines what counts as evidence; this router defines the sweep and the tools.

A scoped check is not a full audit. Record the scope you actually inspected
(files, commands, external checks and date) and list unresolved claims as
unverified. Do not rewrite historical results, silently upgrade a pin, or claim
a release/service fact you did not check.

## Decision table

| Claim or job | Check / tool | Owning source or specialist |
| --- | --- | --- |
| Relative links, moved paths, generated runbook links | `pytest -q tests/test_doc_paths.py -n 0 --no-cov` | The target file on disk; `archivist-file-organizer` for a layout move |
| CLI command, flag, default or subcommand | `python scripts/check_cli_surface.py --check`; spot-check `sandbox <cmd> --help` | `src/mailroom_sandbox/cli.py` and the parser/handler, never the reference alone |
| `docs/cli-reference.md` is stale | `python scripts/check_cli_surface.py` (regenerates) | Generated file — never hand-edit |
| Requirements drift | `python scripts/sync_requirements.py --check` | `pyproject.toml`, then regenerate `requirements/*.txt` |
| Reports hub page/data/snapshot | `python reports/dashboard/build_hub.py --check` | `reports/dashboard/`; regenerate, never hand-edit |
| Runbook catalog and generated runbooks | `sandbox runbook check`; `sandbox runbook list` | `config/runbooks/catalog.yaml`; `sandbox runbook write` regenerates |
| Agent roster, framework tail, Cursor stub | `sandbox subagents doctor --no-global`; `sandbox subagents sync --harness project --check` | `.opencode/agents/<id>.md`, `config/subagents/*`; `harness-doctor` |
| Package version, dependency pin, Python floor | `pyproject.toml`, generated requirements, lockfile, installed version | Owning package; report declared vs installed separately |
| Release/tag claim | `git tag --list`, `gh release view <tag>`, `CHANGELOG.md` heading | The owning repository's release, not a changelog heading alone |
| Vendor snapshot or `_VENDOR_PINS` | `vendor/<pkg>/VENDOR.md`, `_VENDOR_PINS` in `src/mailroom_sandbox/cli.py`, `pytest -q tests/test_vendor_drift.py -n 0 --no-cov` | Owning upstream repo; refresh with `python scripts/sync_vendor.py` or `sandbox fetch-deps`, commit the diff |
| `fetch-deps` behavior | Run `sandbox fetch-deps`; then `git status --short vendor` must be clean at current pins | `_cmd_fetch_deps` / `_refresh_vendor*`; report the exact pins refreshed |
| Dataset revision or row count | `config/datasets.yaml`, `spec.lock.json`, prepared `dataset.jsonl`, run report | Preserve the run's pinned revision; never infer from Hub HEAD |
| Model name, context window or price | `config/models.yaml`, `config/api_prices.yaml`, OpenRouter/AWS owner page with check date | `config/models.yaml` owner; do not copy a price without a date |
| Experiment status or metric | Run ID, `report.json`/`report.md`, experiment log, current-head CI | `eval-judge`; distinguish planned, running, simulated, completed, superseded |
| Quality-gate or CI claim | `.circleci/config.yml` and current-head hosted results | `.circleci/README.md`; do not assume a campaign/benchmark job exists |
| Markdown style/lint | `npx --yes markdownlint-cli2@0.18.1` | `.markdownlint-cli2.yaml` |
| Board card or issue status | `gh issue list`, `governance/TASKS.md`, merged PR/commit evidence | `atom`; close only with a linked evidence trail |

## Full sweep

1. **Inventory the surface.** List tracked Markdown and the instruction files in
   scope:

   ```bash
   git ls-files '*.md' | grep -v '^vendor/'
   git ls-files 'AGENTS.md' 'CLAUDE.md' '.cursor/skills/**/*.md' '.opencode/agents/*.md'
   ```

   Exclude `vendor/`, generated `docs/cli-reference.md`, `CHANGELOG.md` history
   and release archives from hand edits; they are checked or regenerated.
2. **Run the mechanical checks first.** Broken links and stale paths are cheap
   and objective:

   ```bash
   pytest -q tests/test_doc_paths.py -n 0 --no-cov
   python scripts/check_cli_surface.py --check
   python scripts/sync_requirements.py --check
   python reports/dashboard/build_hub.py --check
   sandbox runbook check
   sandbox subagents doctor --no-global
   sandbox subagents sync --harness project --check
   npx --yes markdownlint-cli2@0.18.1
   git diff --check
   ```

   Run the full suite, coverage and campaigns only in hosted CI under
   [`AGENTS.md` tests](../../../AGENTS.md#tests).
3. **Search for the same claim elsewhere.** A stale command usually appears in
   the README, a skill, a runbook, an example and an agent prompt. Search the
   old term, then the new term, before editing:

   ```bash
   rg -n 'old-command|old/path|old-default' --glob '!vendor/**' --glob '!CHANGELOG.md'
   ```

   Include the stale-path list in `tests/test_doc_paths.py` and recently changed
   defaults (`--harness`, record locations, provider names, model ids).
4. **Compare claims with owning sources.** For each non-mechanical claim, open
   the source named in the decision table. A README statement about behavior is
   not evidence for that behavior. Check command defaults against the parser,
   counts against the actual tree, and pins against `VENDOR.md`/`_VENDOR_PINS`.
5. **Update the owning file.** Patch the canonical source, not a generated copy:
   - `docs/cli-reference.md`, `requirements/*.txt`, runbook catalogs and the
     reports hub are generated.
   - Agent prompts live in `.opencode/agents/`; sync project adapters with
     `sandbox subagents sync --harness project`.
   - Layout moves belong to `archivist-file-organizer`; board/README structure
     belongs to `atom`; harness/frontmatter drift belongs to `harness-doctor`.
   - Keep historical results dated and labelled; do not replace them with a
     newer unrelated value.
6. **Regenerate and re-run.** Re-run step 2 after edits. For a vendor refresh,
   run `sandbox fetch-deps` (or `python scripts/sync_vendor.py` from a monorepo
   root), inspect `git diff --stat vendor`, and run the drift guard. For a
   dependency change, regenerate requirements and run the lock/import smoke.
7. **Record the audit boundary.** In the PR or handoff write: files inspected,
   commands run, checkout/ref, external check date, corrections, and anything
   still unverified. A green link check does not prove a model price or release
   still exists.

## Similar-issue sweep

When a review comment or audit finds one stale claim, search for the pattern
before closing it:

- Renamed file or moved section → `tests/test_doc_paths.py` and `rg` the path.
- Changed CLI default/flag → CLI reference generator, README quickstart, skills,
  runbooks and examples.
- Changed provider/model/price → `config/models.yaml`, `config/api_prices.yaml`,
  router tables, runbooks, experiment designs and cost docs.
- Changed agent sync scope → `AGENTS.md`, `CLAUDE.md`, `config/subagents/README.md`,
  `docs/subagents-family-sync.md`, generated Cursor stubs and `scripts/setup_t3.sh`.
- Changed vendor pin → `VENDOR.md`, `_VENDOR_PINS`, `AGENTS.md` vendor text and
  drift tests.
- Closed/merged work → `governance/TASKS.md`, issue body, README status and
  milestone claims.

## Boundaries

- Do not hand-edit `vendor/**`, `requirements/*.txt`, `uv.lock`, `.env`,
  `data/runtime/**` or generated catalogs.
- Do not run the full suite or campaign locally to prove a docs claim; use the
  current-head hosted result and cite the commit.
- Do not silently upgrade dependencies, change a pin, or rewrite an experiment
  lock as part of a docs sweep.
- Do not close an issue or mark a card done without a merged commit, PR or
  explicit not-planned decision in the comment.
- External service facts (release, price, model availability, auth) need an
  owner page/API check with a date, or must stay labelled unverified.
