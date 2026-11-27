---
name: vendor-sync
description: Refresh the sandbox's tracked vendor/ snapshots of llm-mailroom and llm-dojo-scoring from their reviewed standalone refs, then run the drift guards. Use only when the user asks to refresh, update or bump vendored code.
disable-model-invocation: true
---

# vendor-sync

`vendor/` holds **tracked, byte-checked snapshots** of `llm-mailroom` and
`llm-dojo-scoring` (`tests/test_vendor_drift.py`). Never edit them by hand — a hook
blocks it. This skill is the one sanctioned way to change them.

## 0. Preconditions

- The change must already be **committed and merged in the owning repo**
  (`llm-mailroom` for pipeline, `llm-dojo-scoring` for scoring). Never patch the
  snapshot to "fix it here first".
- Establish a clean maintenance scope and identify the package(s) and target
  revision from the authorized request. Ask only when those facts are missing.
- Stop all sandbox processes importing this checkout before changing tracked
  snapshots. Review the complete diff before restarting; staging and rollback
  do not synchronize live imports.

## 1. Set the target pin

Pins live in `_VENDOR_PINS` in `src/mailroom_sandbox/cli.py` as
`(name, ref, url, sha)`. The `sha` is the integrity check: a ref that has moved is
**rejected before any tracked file is replaced**.

```bash
# <url> and <ref> are the package and ref you are pinning; the printed commit must equal
# the `sha` you write into _VENDOR_PINS.
git ls-remote https://github.com/Exios66/<llm-dojo-scoring|llm-mailroom>.git <ref>
```

For a release tag, `ls-remote` prints the tag object and, for annotated tags, a `^{}` line
with the commit; use the `^{}` commit. Edit `ref` and `sha` together. Dojo normally pins a release
tag plus its commit; llm-mailroom pins a reviewed commit SHA (ref and sha are then the same).
To take merged fixes that are not released yet, either package may pin a reviewed `main`
commit (ref and sha the same); say so in `VENDOR.md` and move back to a tag once one is cut.

## 2. Refresh

`sandbox fetch-deps` has **no package filter**: it refreshes every `_VENDOR_PINS` entry.
It does not prompt by itself (Claude Code asks because the command is on the `ask` list).

- **Monorepo** (`../../packages/<name>` exists): `fetch-deps` and
  `python scripts/sync_vendor.py [<name>]` copy the workspace tree (minus the shared vendor
  exclusions: top-level `tests/`/`test/`, `__pycache__`, `*.pyc`, `*.egg-info`,
  `legalbench/reports`) and do **not** compare it with the pin. First verify
  that the workspace package contains the reviewed standalone source at the
  pinned revision. Record the workspace checkout's HEAD and dirty state, then
  compare the filtered runtime-tree bytes with that source. A monorepo HEAD is
  a different revision from the standalone pin and need not equal its SHA;
  matching version/commit metadata alone does not prove matching bytes.
  To refresh one package only, use `python scripts/sync_vendor.py <name>`.
- **Standalone** (no workspace): `fetch-deps` clones each pinned ref and rejects a SHA
  mismatch before replacing tracked files. Because it refreshes both packages, run it only
  when the other package's pin is already what is vendored, then confirm with
  `git status --short -- vendor/` that only the intended package changed. An
  unexpected change is a reason to inspect the refresh and preserve a recovery
  diff, not to discard another package's changes blindly.

```bash
sandbox fetch-deps                          # standalone: both packages, SHA-checked
python scripts/sync_vendor.py <name>        # monorepo: one package, verified source bytes
```

## 3. Update provenance

Make `vendor/README.md` (pin table) and `vendor/<name>/VENDOR.md` (source ref, exact
commit, version, date) match the new pin. Update the root `README.md` too: the two badges,
the vendored-versions table and the "Reviewed dependency refreshes" paragraph name each
version and short commit (`tests/test_vendor.py` checks them against `VENDOR.md`). Open both and check — do not assume the
refresh rewrote them.

## 4. Verify (show the output, do not summarize from memory)

```bash
.venv/bin/python -m pytest -q tests/test_vendor.py tests/test_vendor_drift.py \
  tests/test_vendor_refresh_git.py tests/test_sync_vendor_script.py -n 0 --no-cov
ruff check src tests scripts deploy reports notebooks
```

Expected: the focused tests exit 0 (record skips and their missing source), and
`ruff check` passes. Full-suite/coverage gates run in hosted CI on the final
head, never as an automatic local skill step. Keep the 84% coverage gate and
report missing hosted evidence as pending.

Revalidate every pipeline/scoring hotfix whose target moved; update its
fingerprint and documentation only with evidence, or retire it. Do not accept
an experiment preflight with stale hotfix targets. See
[`vendor-hotfixes`](../../../docs/vendor-hotfixes.md) and
[`scoring-hotfixes`](../../../docs/scoring-hotfixes.md).

`test_vendor_drift.py` also compares against **sibling checkouts** (`../llm-dojo-scoring`,
`../llm-mailroom/src`) when they exist. When the pinned commit exists in the sibling repo it
compares against `git archive` of that commit, so the sibling's checked-out branch does not
matter. When `git archive` of the pinned commit fails for any reason (most often the
commit is missing there — fetch it) it falls back to the working tree, and then a sibling
on a different revision fails the test even though the
vendor refresh is correct — say which sibling is stale rather than "fixing" vendor.

## 5. Commit

Use the repository's `chore(vendor): ...` commit format, listing old/new pins,
source-byte evidence, hotfix status and validation. Do not push unless asked.
