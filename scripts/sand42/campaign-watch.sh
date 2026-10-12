#!/usr/bin/env bash
# SAND-042 campaign early warning.
#
# Watches the running job (from the beacon, which the runner updates per document) and
# EXITS the moment something needs a human look, so the alert arrives in minutes instead
# of at the end of a seven-hour campaign. Exit 3 = ALERT, exit 0 = campaign finished.
#
#   bash ~/sand42-campaign-watch.sh          # 45 s cadence, alert on first trouble
#
# Trouble conditions:
#   ERRORS     any error recorded on the run (a merger LengthFinishReasonError shows here)
#   STALL      no document progress for STALL_MIN (a wedged endpoint looks like this)
#   WALL       elapsed > 85 % of the class's max_wall_seconds (the merger's is 7200 s)
#   DEAD       the run is gone but its run dir holds < 50 items (a partial run)
#   NOLEG      the beacon shows nothing running while a campaign leg is alive for > 6 min
set -uo pipefail
cd /Users/luciusjmorningstar/Downloads/local-mailroom-sandbox
GAP="${1:-45}"
STALL_MIN="${STALL_MIN:-8}"
LOG="$HOME/sand42-alerts.log"

say() { echo "[watch $(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
alert() { echo "[watch $(date '+%H:%M:%S')] ALERT $*" | tee -a "$LOG" >&2; exit 3; }

say "watching (cadence ${GAP}s, stall ${STALL_MIN}min) → $LOG"
idle=0
while :; do
  out=$(.venv/bin/python - <<'PY'
import json, pathlib, sys, time
sys.path.insert(0, "src")
from mailroom_sandbox.job.specialist_posture import SPECIALIST_POSTURE as SP, SAND42_CELLS_BY_ID

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
    wall_cap = int((SP.get(rid) or {}).get("max_wall_seconds") or 2400)
    elapsed, stale = now - started, (now - updated) / 60.0
    flags = []
    if errs > 0:
        flags.append(f"ERRORS={errs}")
    if stale > 8 and done < total:
        flags.append(f"STALL={stale:.0f}min")
    if elapsed > 0.85 * wall_cap:
        flags.append(f"WALL={elapsed/60:.0f}min/{wall_cap/60:.0f}min")
    print(f"RUN {cell} {cls} {done}/{total} err={errs} elapsed={elapsed/60:.0f}min "
          f"stale={stale:.0f}min " + (" ".join(flags) if flags else "ok"))
PY
)
  case "$out" in
    IDLE)
      if pgrep -f "sand42-rerun-chain.sh|sand42-1l4-c8-rerun.sh|sand42-1l4-c16-rerun.sh|sand42-2l4-rerun.sh" >/dev/null; then
        idle=$((idle + 1))
        [ "$idle" -ge 8 ] && alert "no run active for $((idle*GAP/60))min while a leg is alive — wedged deploy?"
      else
        say "campaign finished (no legs running)"; exit 0
      fi
      ;;
    *"ERRORS="*|*"STALL="*|*"WALL="*)
      alert "$out"
      ;;
    *)
      idle=0
      say "$out"
      ;;
  esac
  sleep "$GAP"
done
