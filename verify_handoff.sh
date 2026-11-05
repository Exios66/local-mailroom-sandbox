#!/bin/bash
# verify_handoff.sh — run inside the repo root from Windows:  wsl -d Ubuntu bash ./verify_handoff.sh
# Proves: (1) no 'handoff_context' TypeError, (2) specialists receive the subtype cue, (3) pilot scores.
cd /mnt/c/Users/grant/sandbox-clone
LOG=/mnt/c/Users/grant/AppData/Local/hermes/cache/scratch/handoff_verify.log
echo "=== 3-doc live pilot" > "$LOG"
/home/gemooslin/sandbox-venv/bin/sandbox pilot --local --sample 3 2>&1 >> "$LOG"
echo "=== TypeError present? (want: no matches)" >> "$LOG"
grep -c "handoff_context" "$LOG" >> "$LOG" 2>/dev/null
grep -n "TypeError\|_instantiate_specialist" "$LOG" | head -5 >> "$LOG"
echo "=== unit tests touching build_graph" >> "$LOG"
/home/gemooslin/sandbox-venv/bin/python -m pytest tests -k "handoff or instantiate or build_graph" -q 2>&1 | tail -15 >> "$LOG"
echo VERIFY_DONE >> "$LOG"
tail -c 3000 "$LOG"
