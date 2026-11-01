# Run ledger

Every paid run that passed the spend gate: who signed it (initials), when (UTC), the run and its
locked spec, and how it ended. Appended by `sandbox run start` / `sandbox run resume`; the result
cell is filled when the run reaches a terminal state (✓ done, ✗ failed; blank = still open).
Do not edit rows by hand. Parse with `mailroom_sandbox.job.ledger.rows()`.

| signed_utc | initials | action | run_id | config | spec | rows | api_cap_usd | result |
|---|---|---|---|---|---|---|---|---|
