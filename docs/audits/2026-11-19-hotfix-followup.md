# Experiment hotfix wiring audit: follow-up

Scope: offline review of sandbox execution and scoring hotfixes against PR #367 head
`8fa08acf`, with no change to that PR or to either vendor tree. The PR is not yet a
landed dependency: recheck its final head and merge result before integrating this follow-up.
The campaign contract in that PR defines v9.3/runbook-v2 for new generations and preserves
historical v9.1 locks. This audit does not authorize a paid run or unseal held-out data.

## Reviewed boundaries

- **Vendor behavior:** HF-001–006 target fingerprints, activation, preflight and worker
  checks; corporate type, judge failures, intake preservation, usage hooks, backpressure and
  explicit zero confidence. The watcher-specific HF-005 cannot be imported in this environment
  without the optional observability extra, so its installation and real watcher behavior were
  not verified here. Use `scripts/check_hotfixes.py --require-watcher` in an equipped environment.
- **Scoring:** SHF-001–013 target fingerprints and raw/fixed scopes, subclass corrections,
  truth precedence, error denominators and dual-reporting, with the offline golden cases. A
  passing fingerprint establishes code identity, not semantic correctness of every label or
  experiment outcome.
- **Run identity:** preflight and worker hotfix locks, checkpoint reuse and source provenance.
  A legacy started checkpoint with no locked hotfix basis must not resume in a worker that
  bypasses preflight. An untouched prepared generation remains usable. Any changed hotfix or
  source identity requires a fresh locked generation and a matching deployed worker.
- **Paid-call paths:** chat provider wrappers, the PDF transcriber's early-bound import,
  Decisions transport and per-call usage recording. A pre-imported PDF transcriber now uses
  the pin and call guard; every Decisions HTTP attempt checks the same guard. Successful calls
  still price observed usage after return. Calls already in flight can exceed a cap, and missing
  provider usage or failed requests without usage are not a verified zero cost. Per-document
  call ceilings depend on a document scope; the scope is currently installed for pipeline
  documents, not all isolated-agent paths. These limitations remain for future hardening.
- **Other runtime adapters:** source-window widening/restoration, timeout and provider routing
  are separate from the HF/SHF catalog. The regression tests are useful, but lock identity alone
  does not prove complete long-document reading or actual served-provider behavior. Check the
  ledgers and experiment gates, and retain the open live validations in the campaign contract.

## Findings and corrections

1. A Decisions request did not invoke `before_call`, so an armed cap or pipeline document call
   ceiling could already have been exceeded and another Decisions call would still start. The
   shared transport now checks before each attempt. The normal usage hook continues to price
   successful responses; it is not duplicated at transport level.
2. The PDF transcriber can import the retry function before provider-pin activation. Its saved
   reference bypassed provider pinning, call guard and served ledger. Activation now updates that
   known reference when it still points to the original or this wrapper; unrelated replacements
   are not overwritten. Restore reinstates the original for the wrapped binding.
3. A direct local/remote worker could bypass preflight's legacy scoring-basis check; an older
   lock without vendor/scoring hotfix identities could be resumed against new code. The worker
   now refuses a started checkpoint with either identity absent, before activation and execution.
   An empty `prepared` checkpoint is not mistaken for an executed run.
4. Required vendor fixes marked unavailable passed preflight in the original base. This is
   already addressed in open PR #367, which also adds HF-006 and an optional watcher check;
   this follow-up deliberately does not duplicate that change.

## Verification and constraints

Focused, single-worker, network-free tests exercise the six vendor fixes where dependencies
are present, thirteen scoring fixes and golden raw/fixed comparisons, transport guard, provider
pins, checkpoint reuse, and backpressure. See the handoff for exact commands and results. No
full hosted suite, CircleCI coverage run, live API, Modal worker, watcher, or full-corpus audit
was run here. Historical report artifacts and the open gate tracker, not these tests, determine
campaign readiness. Additional failure paths—missing usage, unscoped isolated calls and other
pre-imported aliases—need separate source-owned work and targeted verification before claiming
that all spend is bounded or every request has a verified provider.

## Resumed-session verification (2026-11-19)

The follow-up changes were re-verified in this checkout after the interrupted review run:

- `pytest tests/test_call_guard.py tests/test_provider_pins.py tests/test_job_runner.py`
  (single worker, network-free, via the sandbox venv with this worktree's `src` and vendored
  trees on `PYTHONPATH`): 105 passed, including the three new tests (Decisions transport guard
  before each attempt, Decisions retry recheck, pre-imported PDF-transcriber binding).
- `scripts/check_hotfixes.py`: HF-001–004 and HF-006 applied, HF-005 unavailable in this
  environment (no optional observability extra), SHF-001–013 current — same as the original
  review's boundaries; the watcher-specific fix still needs `--require-watcher` in an
  equipped environment.
- The runner refusal was checked against `job/checkpoint.py`: the lock's hotfix keys and the
  checkpoint's `state`/`cursor` are the identifiers an unstarted (`prepared`, cursor 0, no
  items) generation and a started one differ on, which is what the refusal keys off.
- Additional vendored-path scan (bounded): the sorter's vision path (`sorter_agent` →
  `base_agent._call_vision_multi`) invokes through the pinned `ChatOpenAI` subclass, so the
  LangChain pin and call guard cover it; `langchain_agents/gmail_triage.py` captures
  completions beneath `retry_chat_completion`, so its transport stays guarded; the raw
  `requests.post` helper `langchain_agents/classifier.py:classify_image` has no callers in
  the sandbox or the vendored graph (the sorter imports only its parsing helpers); vendored
  `scripts/sync_hf_ground_truth.py` binds `retry_chat_completion` by name at module top but
  is a standalone offline script outside the run path. No further unguarded live call path
  was found beyond the limitations already listed above.

Conclusion: the three follow-up corrections stand as reviewed; no additional hotfix to vendored
mailroom or dojo code is required by this audit's scope. The recorded limitations (missing
usage on failed requests, unscoped isolated-agent document ceilings, other pre-imported
aliases, live watcher verification) remain the open hardening items for the campaign contract.
