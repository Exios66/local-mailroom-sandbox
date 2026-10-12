#!/usr/bin/env bash
# SAND-049: per-leg coverage gate for the whole campaign.
#
# The legs that had not yet started carry their own gate, but leg 1 was already running when
# that was added — and editing a running bash script is unsafe, so this verifies every leg
# from outside. For each cell in campaign order it waits for the leg's completion marker, then
# runs the coverage ledger and writes the verdict to the alerts log where the operator and the
# campaign watch both see it. Exits 0 when every leg verified, 3 if any leg fell short (so the
# shortfall arrives as a notification rather than as a footnote seven hours later).
#
#   bash scripts/sand42/leg-boundary-gate.sh
set -uo pipefail
cd /Users/luciusjmorningstar/Downloads/local-mailroom-sandbox
LOG="$HOME/sand42-alerts.log"
say() { echo "[leg-gate $(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }

failed=""
for cell in 1l4-c8 1l4-c16 2l4-c16 2l4-c8 2l4-c32; do
  leg="$HOME/sand42-$cell.log"
  for _ in $(seq 1 900); do                    # 900 × 20 s = 5 h ceiling per leg
    grep -q "RE-RUN COMPLETE" "$leg" 2>/dev/null && break
    sleep 20
  done
  if ! grep -q "RE-RUN COMPLETE" "$leg" 2>/dev/null; then
    say "$cell: never reached its completion marker (leg dead or stalled) — not verifying"
    failed="$failed $cell"
    continue
  fi
  say "── $cell leg finished, verifying coverage ──"
  if .venv/bin/python scripts/sand42/coverage-ledger.py "$cell" 2>&1 | tee -a "$LOG"; then
    say "$cell: ALL CAPTURES, paired n intact"
  else
    say "$cell: GAPS ABOVE — repair with scripts/sand42/topup-one-class.sh <class> $cell"
    failed="$failed $cell"
  fi
done

if [ -n "$failed" ]; then
  say "CAMPAIGN COVERAGE: short in$failed"
  exit 3
fi
say "CAMPAIGN COVERAGE: every leg verified clean"
