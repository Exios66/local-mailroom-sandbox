# Decision reviewer — Pilot 1

## Offline proof (no services or credentials)

```bash
pip install -e '.[dev]'
python -m pytest tests/test_decision_pilot.py tests/test_review_cli.py tests/test_reviewer_spec.py tests/test_decision_backends.py -q
```

The six original, fictional exhibits are in
`data/fixtures/pilot/decision_review.jsonl`: clean accept, disagreement, low
confidence, ineligible label, unavailable reviewer, and no usable text.
The insurance example is synthetic, not evidence about real claims.

`tests/test_decision_pilot.py` uses the actual vendored graph, temporary SQLite
checkpoints/catalog and real bin/archive files. Sorter and specialist calls are
canned; the decision backend is a mock with a registered subclass added by the
test adapter. Sorter confidence is injected at 0.93, and a separate test uses 0.99: `decision_only`
classes reach Lane A at any sorter confidence. The blank
exhibit additionally injects a sorter result: ordinarily the sorter parks blank
text before the decision reviewer. Routing, guards and persistence are not
mocked. External HTTP is blocked.

The tests verify:

- The accepted row reaches procedural report compilation, catalog and archive.
- Each failed condition parks before extraction, retaining the sorter label and
  structured reviewer evidence, with zero LLM-reviewer calls.
- `sandbox review list`, `show` and `resolve` call the actual API endpoints
  in-process (no embedded watcher or listening socket).
- Approval with an explicit class override reaches extraction/archive both
  immediately and after rebuilding the graph over the same SQLite checkpoint.
- Rejection reaches the failed bin, not archive; a second resolve is refused.

These are mechanical integration tests, not calibration or production
qualification. They do not claim to exercise all 13 conditional graph nodes.

## Manual terminal client

Against an API you deliberately started, select its URL and token through
`MAILROOM_API_URL` / `MAILROOM_API_TOKEN`, then:

```bash
sandbox review list
sandbox review show DOC_ID
sandbox review resolve DOC_ID --decision approved --doc-type corporate_record --notes 'operator checked class'
sandbox review resolve DOC_ID --decision rejected --notes 'operator rejected'
```

Choose **one** resolve action per document. Approving resumes extraction and
can make paid model calls on the server. A timeout is not a cancellation; inspect
the queue before retrying. Keep the token in the environment, never the URL.
Use HTTPS for a remote API; HTTP is intended for a trusted loopback connection.

## Reviewer backends

| Backend | Runs on | Correspondence |
| --- | --- | --- |
| `jev` | TypeSafe, a third party (`TYPESAFE_API_KEY`) | Refused until the sanitized corpus exists (SAND-086) |
| `local` | The `sorter_reviewer` agent on your own serving route | Allowed |
| `mock` | Offline tests | Allowed |

`local` needs a model different from the sorter's and an
`agent_routes.sorter_reviewer` entry with provider `modal-vllm` or `vllm` that
serves it; preflight refuses anything else. Set its cutoffs per class. Its
confidence is the model's own and is uncalibrated, so tune them on a labelled
draw before reading review rates as evidence.

## Remaining release and live gates

The current generated vendor snapshot is pinned to standalone decision-reviewer
commit `b1ff69289a7cf33f9d4e93c680187bd56ca3ab7b`. It is an interim branch
snapshot, not a merged release. Upstream merge/push requires explicit approval.

No live `experiment.yaml` is staged and no paid pilot has run. Before creating
or launching the 12-document live pilot, confirm all of:

1. Data terms reviewed and the credential provisioned outside chat.
2. Insurance card-like matches cleared or excluded; correspondence excluded.
3. Pinned source revision and seed-42 draw: four each from contract, corporate
   record and insurance claim; untuned per-class cutoff 0.9.
4. Explicit spend cap and signed experiment review/preflight/launch approval.
5. A running review API sharing the pilot's bins, catalog and SQLite checkpoints.
6. Teardown plan and measured per-document routing/cause/cost evidence.

See `docs/superpowers/plans/2026-10-30-decision-reviewer-poc.md`, Task 9.
Serving proof, sanitized correspondence, shadow pilots and qualification remain
the separate later plans in the design, not deliverables of this offline proof.
