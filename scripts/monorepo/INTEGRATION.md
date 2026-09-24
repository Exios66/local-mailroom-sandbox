# Monorepo `sync_packages.py` hook

After `pull` or `push` refreshes `packages/local-mailroom-sandbox`, propagate
the family subagent roster into every mapped checkout (OpenCode + Cursor).

## One-time wiring (mailroom-dev)

Apply [`sync_packages.patch`](sync_packages.patch) or add manually near
`require_subtree()` in `scripts/sync_packages.py`:

Add near the top of `scripts/sync_packages.py` (with the other imports):

```python
def run_subagents_post_sync() -> None:
    hook = REPO_ROOT / "packages/local-mailroom-sandbox/scripts/monorepo/after_packages_sync.py"
    if not hook.is_file():
        return
    run(
        [sys.executable, str(hook), "--monorepo-root", str(REPO_ROOT)],
        capture=False,
    )
```

Call **`run_subagents_post_sync()`** at the end of `cmd_pull` and `cmd_push`
immediately before each command returns success (`return 0`), after
`save_manifest(manifest)`.

## Manual run

From the monorepo root:

```bash
python3 packages/local-mailroom-sandbox/scripts/monorepo/after_packages_sync.py
```

From a standalone sandbox checkout (sibling `mailroom-dev/` layout):

```bash
sandbox subagents propagate
# or
MAILROOM_DEV_ROOT=../mailroom-dev sandbox subagents propagate
```
