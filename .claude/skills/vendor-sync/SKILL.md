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
- `git status` is clean. Ask the user which package(s) and which target revision.

## 1. Set the target pin

Pins live in `_VENDOR_PINS` in `src/mailroom_sandbox/cli.py` as
`(name, ref, url, sha)`. The `sha` is the integrity check: a ref that has moved is
**rejected before any tracked file is replaced**.

```bash
git ls-remote https://github.com/Exios66/llm-dojo-scoring.git v0.25.0   # confirm the tag's commit
```

Edit `ref` and `sha` together. Dojo pins a release tag plus its commit; llm-mailroom
pins a reviewed commit SHA.

## 2. Refresh

```bash
sandbox fetch-deps        # asks first; workspace mirror if in the monorepo, else the SHA-frozen refs
```

`python scripts/sync_vendor.py` is the monorepo-only path (needs `../../packages`);
in a standalone checkout use `fetch-deps`.

## 3. Update provenance

Make `vendor/README.md` (pin table) and `vendor/<name>/VENDOR.md` (source ref, exact
commit, version, date) match the new pin. Open both and check — do not assume the
refresh rewrote them.

## 4. Verify (show the output, do not summarize from memory)

```bash
.venv/bin/python -m pytest tests/test_vendor.py tests/test_vendor_drift.py \
  tests/test_vendor_refresh_git.py tests/test_vendor_sync_script.py -q
.venv/bin/python -m pytest -q -m "not local_llm"
ruff check src tests scripts deploy reports
```

`test_vendor_drift.py` also compares against **sibling checkouts** (`../llm-dojo-scoring`,
`../llm-mailroom/src`) when they exist. If those are on a different revision than the
pin, the drift test fails even though the vendor refresh is correct — say which
sibling is stale rather than "fixing" vendor.

## 5. Commit

One commit titled `vendor: <package> -> <ref> (<short sha>)`, body listing old and new
pins and the diffstat. Do not push unless asked.
