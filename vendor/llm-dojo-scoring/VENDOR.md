# Vendored: llm-dojo-scoring (DMR-057 self-containment)

The `src/llm_dojo_scoring/` tree below is a **tracked snapshot** of the
deterministic scoring engine the sandbox imports at runtime
(`experiment`, `serving`, `extraction_metrics`, `mailroom`, `get_suite`,
`headline_metrics`, …). Shipping it in-repo removes the
`llm-dojo-scoring @ git+...` pip pin — the sandbox no longer needs the
network or an install to score runs.

- Upstream: https://github.com/Exios66/llm-dojo-scoring
- Pin: **workspace snapshot — see monorepo** (tracks `packages/llm-dojo-scoring`
  in the Digital-Mailroom monorepo — the development source of truth;
  hub#62 doctrine). Current snapshot: upstream dojo commit `852b05274a97`
  (branch `claude/cool-wozniak-o044u4`), i.e. the unreleased fixes toward
  **v0.22.0** (`[Unreleased]` in the dojo CHANGELOG; the package still
  reports `__version__ = "0.21.0"`). Interim: the pin becomes the `v0.22.0`
  tag once it is cut — re-vendor from the tag then.
- Lineage: upstream tag `v0.15.0` (`9db1417b`) was the last tagged pin; the
  vendored tree mirrors the monorepo workspace snapshot, refreshed with the
  DMR-061 emitter counters on 2026-09-14, the SAND-042 schema-adherence
  line (v0.3.0), and the v0.22.0 pre-tag fixes (strict `metric_id_for`,
  required emitter provenance, `identity_mixed` serving legs) and the
  eval-environment prompt lineage (`llm_dojo_scoring.prompts.lineage` +
  `prompts/eval_environment_lineage.json`, 40 versions, eval-environment
  `bdba24c`) so the drift
  guard stays byte-identical.
- Layout: upstream package dir relocated under `src/` (mirrors
  `vendor/llm-mailroom/src`); upstream `tests/`, `examples/`, `docs/` are not
  vendored.
- Refresh: `python scripts/sync_vendor.py` from the monorepo root — mirrors
  the workspace onto this tree carrying BOTH content updates AND deletions
  (DMR-070). `sandbox fetch-deps` prefers the same workspace mirror when the
  monorepo layout is detected and falls back to a loud tag-based refresh for
  standalone clones.
- The sandbox prepends `vendor/llm-dojo-scoring/src` to `sys.path` on package
  import (`mailroom_sandbox/__init__.py`), so the vendored engine shadows any
  installed `llm_dojo_scoring`.