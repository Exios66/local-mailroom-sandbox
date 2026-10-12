#!/usr/bin/env bash
# SAND-053: the campaign babysitter.
#
# Two roles, deliberately split:
#   * `campaign-watch.sh` is the PAGER — it exits 3 on the first trouble so the operator is
#     notified, which means it stops watching at exactly the moment things went wrong.
#   * this is the SITTER — it never exits early. It keeps a heartbeat, surfaces trouble into
#     the alerts log (once per distinct condition, not once per tick), verifies each leg's
#     coverage the moment that leg finishes, and only stops when the campaign is over.
#
#   bash scripts/sand42/campaign-sitter.sh [cadence_seconds]
set -uo pipefail
cd /Users/luciusjmorningstar/Downloads/local-mailroom-sandbox
GAP="${1:-45}"
STALL_MIN="${STALL_MIN:-15}"
BEAT_EVERY="${BEAT_EVERY:-300}"
LOG="$HOME/sand42-sitter.log"
ALERTS="$HOME/sand42-alerts.log"
LEGS='sand42-rerun-chain\.sh|sand42-1l4-c8-rerun\.sh|sand42-1l4-c16-rerun\.sh|sand42-2l4-rerun\.sh'
CELLS=(1l4-c8 1l4-c16 2l4-c16 2l4-c8 2l4-c32)

say()   { echo "[sitter $(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
alert() { echo "[sitter $(date '+%H:%M:%S')] ALERT $*" | tee -a "$LOG" "$ALERTS" >&2; }

# bash 3.2 is what `bash` resolves to on macOS: no associative arrays, so `verified` is a
# space-delimited list and membership is a case match.
verified=""
say "babysitting · cadence ${GAP}s · stall ${STALL_MIN}min · heartbeat ${BEAT_EVERY}s → $LOG"
last_beat=0          # 0, so the first tick logs health and proves the sitter can read the beacon
last_alert=""

while :; do
  if ! pgrep -f "$LEGS" >/dev/null 2>&1; then
    say "all legs exited — final coverage pass"
    for c in "${CELLS[@]}"; do
      case " $verified " in *" $c "*) continue ;; esac
      .venv/bin/python scripts/sand42/coverage-ledger.py "$c" 2>&1 | tee -a "$LOG"
      verified="$verified $c"
    done
    say "babysitter done — every leg verified, or its gaps are in the log above"
    break
  fi

  health=$(STALL_MIN="$STALL_MIN" .venv/bin/python - <<'PY'
import json, pathlib, os, sys, time
sys.path.insert(0, "src")
from mailroom_sandbox.job.specialist_posture import SPECIALIST_POSTURE as SP
stall = float(os.environ.get("STALL_MIN", "15"))
jobs = pathlib.Path.home() / ".mailroom" / "jobs"
now = time.time()
running = []
for f in jobs.glob("sand42-*-awq-*.json"):
    try:
        d = json.loads(f.read_text())
    except ValueError:
        continue
    if d.get("state") == "running":
        running.append(d)
if not running:
    print("IDLE")
    raise SystemExit(0)
for d in running:
    rid = str(d.get("job_id") or "")
    cls = rid.split("sand42-50-")[-1].rsplit("-specialist-awq-", 1)[0]
    cell = rid.rsplit("-awq-", 1)[-1]
    done, total = int(d.get("done") or 0), int(d.get("total") or 0) or 50
    errs = int(d.get("errors") or 0)
    started = float(d.get("started_at") or now)
    updated = float(d.get("updated_at") or now)
    cap = int((SP.get(rid) or {}).get("max_wall_seconds") or 2400)
    elapsed, stale = now - started, (now - updated) / 60.0
    flags = []
    if errs:
        flags.append(f"ERRORS={errs}")
    if stale > stall and done < total:
        flags.append(f"STALL={stale:.0f}min")
    if elapsed > 0.85 * cap:
        flags.append(f"WALL={elapsed/60:.0f}min/{cap/60:.0f}min")
    print(f"RUN {cell} {cls} {done}/{total} err={errs} elapsed={elapsed/60:.0f}min "
          f"stale={stale:.0f}min " + (" ".join(flags) if flags else "ok"))
PY
)

  case "$health" in
    IDLE) : ;;
    *ERRORS=*|*STALL=*|*WALL=*)
      # once per distinct condition: an alert repeated every 45 s is one nobody reads
      [ "$health" != "$last_alert" ] && { alert "$health"; last_alert="$health"; }
      ;;
    *)
      last_alert=""
      if [ $(( $(date +%s) - last_beat )) -ge "$BEAT_EVERY" ]; then
        say "$health"; last_beat=$(date +%s)
      fi
      ;;
  esac

  # A leg is verified the moment it finishes, not at the end of the campaign: the card rewrite
  # is what makes the check meaningful, and every leg prints its marker after that.
  for c in "${CELLS[@]}"; do
    case " $verified " in *" $c "*) continue ;; esac
    grep -q "RE-RUN COMPLETE" "$HOME/sand42-$c.log" 2>/dev/null || continue
    say "── $c leg finished — verifying coverage ──"
    .venv/bin/python scripts/sand42/coverage-ledger.py "$c" 2>&1 | tee -a "$LOG"
    verified="$verified $c"
  done

  sleep "$GAP"
done
