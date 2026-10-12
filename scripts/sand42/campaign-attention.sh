#!/usr/bin/env bash
# Wake instrument for the orchestrator. The sitter and pager own *detection*; this only
# decides when the orchestrator comes back. It exits — raising a completion notification —
# at the next leg boundary, on a raised page, or on the first error in any leg, so the
# orchestrator resumes exactly when something changed instead of polling for it.
#
# Exit 0 always: the exit *is* the signal, and its stdout line says which one fired.
set -u

CADENCE="${1:-30}"
# Baseline is passed in, not counted at startup: a leg that completes between the orchestrator's
# last look and this process's first tick would otherwise be folded into the baseline and missed.
BASE="${2:-}"
CELLS="1l4-c8 1l4-c16 2l4-c16 2l4-c8 2l4-c32"
SENTINEL="$HOME/.sand42-page-me"

markers() { cat "$HOME"/sand42-*.log 2>/dev/null | grep -c "RE-RUN COMPLETE"; }

base="${BASE:-$(markers)}"
echo "[attention] watching · cadence ${CADENCE}s · baseline markers $base"

while :; do
  sleep "$CADENCE"
  if [ -f "$SENTINEL" ]; then
    echo "WOKE: page raised — $(cat "$SENTINEL" 2>/dev/null)"
    exit 0
  fi
  now="$(markers)"
  if [ "$now" -gt "$base" ]; then
    echo "WOKE: leg boundary (completion markers $base -> $now)"
    exit 0
  fi
  for c in $CELLS; do
    f="$HOME/sand42-$c.log"
    if [ -f "$f" ] && grep -qE "errors=[1-9]" "$f" 2>/dev/null; then
      echo "WOKE: error in leg $c — $(grep -E "errors=[1-9]" "$f" | tail -1)"
      exit 0
    fi
  done
done
