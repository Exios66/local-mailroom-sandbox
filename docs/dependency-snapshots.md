# Stable dependency snapshots

The sandbox can fetch released Dojo and pipeline code into a verified local
cache. A fresh checkout still works offline with its tracked vendor snapshots.
This feature implements [SAND-104 / issue #285](https://github.com/Exios66/local-mailroom-sandbox/issues/285).
It changes source acquisition and provenance; scoring and pipeline logic remain
owned by their upstream repositories.

## Fetch and inspect

```bash
sandbox deps fetch --component dojo --version v0.28.1
sandbox deps fetch --component pipeline --version v0.9.3
sandbox deps fetch --component all --stable
sandbox deps fetch --check                   # read-only; asks GitHub for latest stable
sandbox deps fetch --check --offline         # read-only; local layers only
sandbox deps fetch --component dojo --check --version v0.28.1
```

Normal fetching resolves a stable, published GitHub release, never `main`.
An exact `--version` means a release tag, including its `v` prefix. Drafts and
prereleases are refused. The first `--stable` fetch resolves GitHub's latest
stable release; later calls reuse that verified resolution offline. Use
`--refresh` to explicitly query GitHub again. An exact-tag cache hit is also
offline. A moved tag or changed bytes for an already cached release is refused.

The report lists the vendor pin, installed distribution, verified cache entries,
selected source and latest release date. `--check` creates no files. Its latest
lookup can report an unavailable network without failing the command. A requested
`--version` match currently means that exact tag exists in the verified cache;
a missing match returns 1. A newer available release alone never returns failure.
`--offline` requires `--check`; it suppresses all network access.

Cache entries live under
`data/cache/snapshots/<component>/<tag>-<12-character-commit>/`, independent of
`MAILROOM_BASE_DIR`. Each contains `source/` and `snapshot.lock.json`. Fetch output
includes `lock_path`, commit, package version, tag, artifact digest, verification
method and fetch/publication dates. No package installation is performed.

## Select a release explicitly

Fetching a different release does **not** automatically upgrade imports. The
normal resolution order for each component is:

1. Explicit `DOJO_SRC` or `MAILROOM_SRC` source tree.
2. Installed distribution matching the reviewed version/commit, or the explicitly
   selected snapshot's version/commit, with a valid import/runtime layout.
3. Verified cache matching that reviewed commit, or the explicitly selected lock.
4. Tracked vendor snapshot.
5. An aggregated diagnostic naming the rejected layers when runtime source is
   required. Inspection and fetch remain available for repairing a missing tree.

Select another cached release before starting a **new process**:

```bash
export SANDBOX_DOJO_SNAPSHOT=/absolute/path/to/dojo/entry/snapshot.lock.json
export SANDBOX_PIPELINE_SNAPSHOT=/absolute/path/to/pipeline/entry/snapshot.lock.json
sandbox deps fetch --check --offline
sandbox run preflight --config config/runs/example.yaml
```

Use the actual `lock_path` returned by fetch and an existing run configuration;
`example.yaml` above is a placeholder. The two variables also work in the sandbox
`.env`, with real environment variables taking precedence. Selection runs at
package bootstrap, before family imports; changing a variable inside an already
running Python interpreter does not switch its loaded modules. Invalid caches
fall back with diagnostics. `SANDBOX_DOJO_SOURCE=vendored` disables its cache and
installed layers; the existing `installed` mode still explicitly permits an
off-pin installed Dojo. `DOJO_SRC` remains the highest-priority development escape
hatch. Pipeline source roots accept either `src/` or a repository containing it.

The cache defaults deliberately match the reviewed `PINS` in
`src/mailroom_sandbox/snapshots.py`, even if the vendor directory is unavailable.
Tests keep their commit identities aligned with `_VENDOR_PINS`. Fetching never
rewrites these pins, `vendor/`, dependencies, or existing run locks. A reviewed
vendor refresh still uses `sandbox fetch-deps` or `scripts/sync_vendor.py`.
Stop all sandbox processes using that checkout first, complete and review the
refresh, then restart. Vendor replacement has a brief destination gap and can
otherwise mix old/new imports; staging and rollback protect failure recovery,
not concurrent readers. Immutable cache entries avoid replacing an existing
selected tree, while fetching a new entry leaves the old selection intact.

## Run locks and remote execution

New `spec.lock.json` files record `dependency_sources` for **both** components:
source layer, package version, exact commit, and a digest of the selected source
files. Cached releases additionally record their verified artifact digest.
Installed, vendored and explicit development sources hash their runtime files,
resources, relative names and executable modes; edits, additions and deletions
invalidate the lock even when version/commit metadata is unchanged. Installed
fingerprints cover only the component's own package roots (including newly added
files), not unrelated distributions in site-packages. Missing ownership metadata
or unreadable/missing source fails closed. Absolute paths and generated
`__pycache__` files are excluded so an identical worker copy keeps its identity.
`sandbox run status` includes this frozen provenance. Preflight reuse and job
execution refuse a changed source or damaged cache before executing work. Restore
the original selection in a new process to resume; a deliberate `--force`
preflight creates a new generation through the existing archive/re-lock workflow.
Historical locks without the new field remain readable. Locks made by earlier
development builds that contain `dependency_sources` but omit mutable-source
digests refuse reuse; explicitly archive/re-lock a new generation to adopt the
stronger identity rather than editing the old lock.

Local endpoint jobs can use selected snapshots with the existing serving routes,
including an external Modal vLLM endpoint. For `job.mode: modal`, deploy the job
worker with the same snapshot variables. `deploy/modal_job.py` bundles selected
verified cache entries and fixes their container lock paths. If bootstrap chose a
matching installed release instead, it also bundles that distribution's own
runtime roots and `.dist-info` metadata, preserving the installed source layer
and any explicitly selected snapshot target. It never fetches latest inside the
worker or uploads unrelated distributions or the rest of the local cache.
`SANDBOX_INSTALLED_DOJO_ROOT` and `SANDBOX_INSTALLED_PIPELINE_ROOT` are reserved
image settings emitted by the bundler; package bootstrap adds these metadata/import
roots before choosing sources. They are not dotenv settings or a replacement for
operator-facing source selection. Metadata containing URL credentials is refused
before export. A stale worker
image refuses a mismatched run instead of silently using different code. An
explicit development tree or installed source must likewise match the worker's
source identity; the default worker image remains vendor-based. Deployment and
paid runs retain their existing human spend gates.

## Verification and failure recovery

For Dojo, fetch requires the owner's `release-manifest.json`, `SHA256SUMS`, and
manifest-named wheel or sdist. The manifest's package, tag and commit must match
the peeled GitHub tag. Both checksum listings and the artifact size/digest are
checked **before extraction**. These checks provide integrity within the owner's
release; they are not an independent signature or publisher attestation.

As verified on 2026-11-10, Dojo
[`v0.28.1`](https://github.com/Exios66/llm-dojo-scoring/releases/tag/v0.28.1)
publishes those assets. Pipeline
[`v0.9.3`](https://github.com/Exios66/llm-mailroom/releases/tag/v0.9.3)
has none. Its fallback peels the release tag (including annotated tags) to an
immutable commit, downloads that commit's GitHub archive and records a **locally
computed** SHA-256. This is weaker than an owner-published checksum and is labeled
in the lock. Mutable `target_commitish: main` is never treated as commit proof.
Pipeline publishing is tracked in
[llm-mailroom #225](https://github.com/Exios66/llm-mailroom/issues/225).
The archive's package version is read separately from its release tag.

Downloads are limited to 64 MiB; extraction to 256 MiB and 20,000 members.
Only regular files/directories are accepted. Links, special files, duplicate
files, traversal paths and precompiled bytecode are refused. HTTP follows only
HTTPS GitHub download hosts and sends no authentication tokens. Public releases
are supported; GitHub API limits/authentication failures are surfaced as download
errors rather than prompting for credentials. Timeouts are bounded per request.

Extraction and validation happen in a temporary sibling directory before atomic
rename. Failed fetches preserve existing entries and vendor files. Cache reuse
checks the complete source inventory and executable modes; generated
`__pycache__` files are excluded. Source selection and checks do not repair or
remove damaged caches. Preserve their diagnostics, then explicitly fetch a clean
entry after moving the damaged directory aside. Never delete another run's
cache or overwrite an immutable lock to get past a drift refusal.

Focused offline regressions live in `tests/test_snapshots.py` and
`tests/test_dependency_sources.py`. Full-suite coverage remains a hosted CI gate.
