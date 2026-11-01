# Run ledger

Every paid run that passed the spend gate: who signed it (initials), when (UTC), the run and its
locked spec, and how it ended. Appended by `sandbox run start` / `sandbox run resume`; the result
cell is filled when the run reaches a terminal state (✓ done, ✗ failed; blank = still open).
Do not edit rows by hand. Parse with `mailroom_sandbox.job.ledger.rows()`.

| signed_utc | initials | action | run_id | config | spec | rows | api_cap_usd | result |
|---|---|---|---|---|---|---|---|---|
| 2026-11-01T08:42:40Z | JB | start | extraction-gate-specialist-insurance-claim-qwen | config/runs/extraction-gate-specialist-insurance-claim-qwen.yaml | 295e169d5f81 | 60 | 0.05 | ✓ |
| 2026-11-01T08:43:07Z | JB | start | extraction-gate-specialist-correspondence-qwen | config/runs/extraction-gate-specialist-correspondence-qwen.yaml | d31affa9a548 | 60 | 0.05 | ✓ |
| 2026-11-01T08:44:03Z | JB | start | extraction-gate-specialist-corporate-record-qwen | config/runs/extraction-gate-specialist-corporate-record-qwen.yaml | b7db57702771 | 40 | 0.1 | ✓ |
| 2026-11-01T08:44:34Z | JB | start | extraction-gate-specialist-contract-qwen | config/runs/extraction-gate-specialist-contract-qwen.yaml | b994376771b9 | 40 | 0.1 | ✓ |
| 2026-11-01T08:45:18Z | JB | start | extraction-gate-specialist-merger-agreement-qwen | config/runs/extraction-gate-specialist-merger-agreement-qwen.yaml | cf1410a4e705 | 20 | 0.2 | ✓ |
| 2026-11-01T08:47:51Z | JB | start | extraction-gate-luna-v1.0.0-baseline | config/runs/extraction-gate-luna-v1.0.0-baseline.yaml | b6cf7cc75817 | 220 | 0.35 | ✓ |
