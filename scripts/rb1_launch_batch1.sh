#!/usr/bin/env bash
# Launch campaign rb1 batch 1 (runbook R11, R12, R14, R15 and the R41 prompt A/Bs) on OpenRouter.
#
#   scripts/rb1_launch_batch1.sh --dry-run                 # preflight every config + cost estimate; spends nothing
#   scripts/rb1_launch_batch1.sh --initials JB             # preflight, estimate, typed "yes", then start each run
#   scripts/rb1_launch_batch1.sh --initials JB --only r41  # a subset: run ids containing "r41"
#   scripts/rb1_launch_batch1.sh --initials JB --exclude r15-deepseek --exclude r15-glm
#
# The initials belong to the person launching (2-6 capital letters); nothing here invents them.
# Every run is started sequentially with its own served-provider ledger
# (SANDBOX_SERVED_LOG=data/runtime/<key>/served-<run_id>.jsonl), and the script stops at the first
# preflight, estimate or start failure. Needs OPENROUTER_API_KEY for the real launch (the estimate's
# key-headroom check and each run's spend gate read it). Run from anywhere; it cds to the repo root
# and sets PYTHONPATH=$PWD/src, so a worktree runs its own code.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
SANDBOX="${SANDBOX:-$ROOT/.venv/bin/sandbox}"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"

# Launch order: cheap sorter pilots first, the pairing arm (R14 t0 rep1) before R11, the long and
# dear R15 transfer arms last.
ORDER=(
  rb1-r14-qwen3.7-flash-t0-rnone-rep1
  rb1-r11-sorter-v0.1-pool
  rb1-r14-qwen3.7-flash-t0-rnone-rep2
  rb1-r14-qwen3.7-flash-t0-rnone-rep3
  rb1-r14-qwen3.7-flash-t0-rmedium
  rb1-r14-qwen3.7-flash-t0.2-rnone
  rb1-r14-qwen3.7-flash-t0.2-rmedium
  rb1-r14-qwen3.7-flash-t0.4-rnone
  rb1-r14-qwen3.7-flash-t0.4-rmedium
  rb1-r14-deepseek-v4.1-flash-t0-rnone
  rb1-r14-glm-5.3-flashx-legal-t0-rnone
  rb1-r12-insurance-v0-look1
  rb1-r12-correspondence-v0-look1
  rb1-r12-corporate-v0-look1
  rb1-r12-contracts-v0-look1
  rb1-r12-merger-v0-look1
  rb1-r41-corporate-condensed-v1-look1
  rb1-r41-corporate-condensed-v2-look1
  rb1-r41-correspondence-condensed-v3-look1
  rb1-r41-correspondence-condensed-v4-look1
  rb1-r41-contracts-v33-simplified-look1
  rb1-r41-contracts-condensed-v1-look1
  rb1-r41-insurance-condensed-v3-look1
  rb1-r41-insurance-condensed-v5-look1
  rb1-r41-corporate-condensed-v1-look2
  rb1-r41-corporate-condensed-v2-look2
  rb1-r41-correspondence-condensed-v3-look2
  rb1-r41-correspondence-condensed-v4-look2
  rb1-r41-contracts-v33-simplified-look2
  rb1-r41-contracts-condensed-v1-look2
  rb1-r41-insurance-condensed-v3-look2
  rb1-r41-insurance-condensed-v5-look2
  rb1-r15-qwen3.7-flash-cap4k
  rb1-r15-qwen3.7-flash-cap8k
  rb1-r15-qwen3.7-flash-full
  rb1-r15-deepseek-v4.1-flash-full
  rb1-r15-glm-5.3-flashx-legal-full
)

usage() { sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; }

INITIALS="" DRY_RUN=0 ONLY=() EXCLUDE=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --initials) INITIALS="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --only) ONLY+=("${2:?--only needs a pattern}"); shift 2 ;;
    --exclude) EXCLUDE+=("${2:?--exclude needs a pattern}"); shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -n "$INITIALS" && ! "$INITIALS" =~ ^[A-Z]{2,6}$ ]]; then
  echo "--initials must be 2-6 capital letters (got '$INITIALS')" >&2; exit 2
fi
if [[ $DRY_RUN -eq 0 && -z "$INITIALS" ]]; then
  echo "a launch needs --initials XX from the person authorizing the spend (or use --dry-run)" >&2; exit 2
fi

key_of() { local rid="$1"; echo "${rid%%-*}-$(echo "$rid" | cut -d- -f2)"; }   # rb1-r14-... -> rb1-r14
ledger_of() { echo "data/runtime/$(key_of "$1")/served-$1.jsonl"; }

RUNS=()
for rid in "${ORDER[@]}"; do
  keep=1
  if [[ ${#ONLY[@]} -gt 0 ]]; then keep=0; for p in "${ONLY[@]}"; do [[ "$rid" == *"$p"* ]] && keep=1; done; fi
  for p in "${EXCLUDE[@]+"${EXCLUDE[@]}"}"; do [[ "$rid" == *"$p"* ]] && keep=0; done
  [[ $keep -eq 1 ]] || continue
  [[ -f "config/runs/$rid.yaml" ]] || { echo "missing config/runs/$rid.yaml" >&2; exit 1; }
  RUNS+=("$rid")
done
[[ ${#RUNS[@]} -gt 0 ]] || { echo "no runs selected" >&2; exit 2; }
echo "rb1 batch 1: ${#RUNS[@]} run(s) selected"

# 1. preflight every selected config (locks its documents; no spend)
for rid in "${RUNS[@]}"; do
  ledger="$(ledger_of "$rid")"; mkdir -p "$(dirname "$ledger")"
  if ! out="$(SANDBOX_SERVED_LOG="$ledger" "$SANDBOX" run preflight --config "config/runs/$rid.yaml" 2>&1)"; then
    echo "$out" | tail -20 >&2; echo "PREFLIGHT FAILED: $rid" >&2; exit 1
  fi
  echo "  preflight ok  $rid"
done

# 2. the cost estimate, total first (scripts/estimate_spend.py; checks key headroom when the key is set)
CONFIGS=(); for rid in "${RUNS[@]}"; do CONFIGS+=("config/runs/$rid.yaml"); done
set +e
est="$("$PYTHON" scripts/estimate_spend.py "${CONFIGS[@]}" 2>&1)"; est_rc=$?
set -e
echo; echo "$est" | grep -E '^(TOTAL|key remaining|note:)' || true
echo "  (per-run rows: python scripts/estimate_spend.py <configs>; it prices an unpinned sorter at the long V15"
echo "   prompt, so sorter rows read high; the per-config headers carry the condensed-prompt estimate)"
if [[ $DRY_RUN -eq 1 ]]; then
  [[ $est_rc -eq 0 ]] || echo "WARNING: the estimate does not fit the key's spendable headroom (a launch would stop here)"
  echo "dry run: preflight only, nothing started"; exit 0
fi
if [[ $est_rc -ne 0 ]]; then
  echo "$est" | tail -5 >&2; echo "ESTIMATE FAILED or does not fit the key headroom; nothing started" >&2; exit 1
fi

# 3. typed confirmation
read -r -p "Start ${#RUNS[@]} paid run(s) as $INITIALS? Type yes to continue: " answer
[[ "$answer" == "yes" ]] || { echo "not confirmed; nothing started"; exit 1; }

# 4. start each run sequentially; stop at the first failure
for rid in "${RUNS[@]}"; do
  ledger="$(ledger_of "$rid")"
  echo; echo "=== $rid  (ledger $ledger)"
  SANDBOX_SERVED_LOG="$ledger" "$SANDBOX" run preflight --config "config/runs/$rid.yaml" >/dev/null \
    || { echo "PREFLIGHT FAILED: $rid; stopping" >&2; exit 1; }
  SANDBOX_SERVED_LOG="$ledger" "$SANDBOX" run start --config "config/runs/$rid.yaml" --initials "$INITIALS" \
    || { echo "START FAILED: $rid; stopping (resume: sandbox run resume --config config/runs/$rid.yaml --initials $INITIALS)" >&2; exit 1; }
done
echo; echo "rb1 batch 1: all ${#RUNS[@]} run(s) done. Verdicts: python scripts/rb1_promote.py --look 1|2"
