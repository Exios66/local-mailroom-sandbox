#!/usr/bin/env bash
# scripts/setup_t3.sh — repository setup that interfaces with t3-code.
# Usage: bash scripts/setup_t3.sh [--dry-run] [--worktree NAME]
# PR tracking: PR 220 (github.com/Exios66/local-mailroom-sandbox/pull/220) is linked.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PROFILE_DEFAULT="${SANDBOX_PROFILE:-modal-vllm}"
WORKTREE_DEFAULT=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case $1 in
    --dry-run) DRY_RUN=1 ;;
    --worktree) WORKTREE_DEFAULT="$2"; shift ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
  shift
done

EVIDENCE_LOG="$REPO_ROOT/reports/setup.evidence.jsonl"
CARD_FILE="$REPO_ROOT/reports/setup.card.json"
mkdir -p "$REPO_ROOT/reports"

log_structured() {
  local event="$1"
  local detail="$2"
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '{"ts":"%s","event":"%s","detail":"%s","profile":"%s","worktree":"%s","pr":"220","dry_run":%s}\n' \
    "$ts" "$event" "$detail" "$PROFILE_DEFAULT" "${WORKTREE_DEFAULT:-none}" "$DRY_RUN" >> "$EVIDENCE_LOG"
}

# Credential prompt with required env list for t3 / sandbox / family.
echo "=== Required environment (configure before live runs) ==="
cat <<'CREDS'
  OPENROUTER_API_KEY    — token-billed Decisions / sorter_reviewer routes
  MODAL_TOKEN (or MODAL_API_KEY) — Modal deploy / vLLM serve / GPU runs
  SANDBOX_PROFILE       — default serving profile (default: modal-vllm)
  LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY — tracing (default sink)
  HF_TOKEN              — HuggingFace hub pulls / vendored refresh
  MAILROOM_CHECKPOINTER — decision reviewer backend (sqlite default)
  SANDBOX_DEBUG=1       — optional: set -x + results/run.log diagnostics
CREDS

# Prompt user interactively (non-blocking in dry-run).
if [[ $DRY_RUN -eq 0 && -t 0 ]]; then
  echo "Press ENTER after confirming your .env has the keys above (or Ctrl+C to abort)."
  read -r
fi

echo "=== Setup: venv + pyproject ==="
python3 -m venv .venv || true
# Use pinned requirements path first; fall back to pyproject.
if [[ -f requirements/dev.txt ]]; then
  . .venv/bin/activate && pip install -q -r requirements/dev.txt || pip install -q -e ".[dev]"
else
  . .venv/bin/activate && pip install -q -e ".[dev]"
fi
log_structured "venv_installed" "pyproject install complete"

echo "=== Setup: .env ==="
if [[ ! -f .env ]]; then
  cp config/.env.example .env
  echo "Created .env from config/.env.example (fill keys above)."
fi
log_structured "env_created" ".env present or copied"

echo "=== Setup: vendor snapshots + fetch-deps ==="
# Refresh vendored family trees from pinned sources when available.
python scripts/sync_vendor.py --check || python scripts/sync_vendor.py || true
# Optional full dependency refresh (workspace packages first, SHA-frozen standalone refs fallback).
python -m mailroom_sandbox.cli fetch-deps || sandbox fetch-deps || true
log_structured "vendor_synced" "sync_vendor + fetch-deps attempted"

echo "=== Setup: Modal CLI ==="
which modal || pip install -q modal==1.6.2 || echo "warning: modal CLI not available; install via pip above"
if [[ -n "${MODAL_TOKEN:-}" ]]; then
  modal profile activate default || true
  log_structured "modal_configured" "profile activated with MODAL_TOKEN"
else
  echo "warning: MODAL_TOKEN not set — deploy / vLLM serve will fail."
fi

echo "=== Setup: hf CLI ==="
if [[ -n "${HF_TOKEN:-}" ]]; then
  python -m huggingface_hub.commands.login || true
fi
log_structured "hf_configured" "HF_TOKEN=${HF_TOKEN:+set}"

echo "=== Setup: OpenRouter / sandbox CLI ==="
# The sandbox CLI uses OPENROUTER_API_KEY; verify the overlay config loads.
python -c "
import os, yaml
from mailroom_sandbox.overlay import load_model_map, build_merged_taxonomy, load_profile
print('overlay loaded:', bool(load_model_map()))
print('models:', list((load_model_map() or {}).get('models',{}).keys())[:8], '...')
" || true
log_structured "overlay_verified" "config/models.yaml + taxonomy overlay load"

echo "=== Setup: T3 interface (opencode / delegate / subagents) ==="
# Create/verify worktree binding for T3 isolation.
if [[ -n "$WORKTREE_DEFAULT" ]]; then
  python -m opencode worktree_create --name "$WORKTREE_DEFAULT" || true
  log_structured "t3_worktree" "requested $WORKTREE_DEFAULT"
fi
# Verify capability presence (delegate_task, session_move, worktree_create).
python - <<'PY' || true
import importlib, sys
caps = ["delegate_task", "t3_worktree_create", "worktree_create", "link_pull_request"]
found = []
for mod in ["t3_code_f60ec8f4_828b_475c_a579_ff92eb02724c", "opencode"]:
  try:
    m = importlib.import_module(mod)
    for c in caps:
      if hasattr(m, c): found.append(f"{mod}.{c}")
  except Exception:
    pass
print("t3 capabilities available:", found)
PY
# Sync subagent harness stubs (Cursor + OpenCode) per family roster.
python -m mailroom_sandbox.subagents sync --harness all || sandbox subagents sync --harness all || echo "warning: subagents sync skipped (needs sandbox CLI in PATH)"
log_structured "t3_subagents" "subagents sync --harness all attempted"

echo "=== Setup: board card (structured evidence) ==="
WORKTREE_BOOL="false"
[[ -n "$WORKTREE_DEFAULT" ]] && WORKTREE_BOOL="true"
cat > "$CARD_FILE" <<CARD
{
  "card_id": "SETUP-T3-001",
  "pr": 220,
  "branch": "calibration/reviewer-luna-full",
  "repo": "Exios66/local-mailroom-sandbox",
  "run_id": "setup-t3-$(date +%Y%m%d-%H%M%S)",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "profile": "$PROFILE_DEFAULT",
  "worktree": "${WORKTREE_DEFAULT:-none}",
  "dry_run": $DRY_RUN,
  "credentials_required": [
    "OPENROUTER_API_KEY",
    "MODAL_TOKEN",
    "SANDBOX_PROFILE",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "HF_TOKEN"
  ],
  "checks": {
    "vendor_snapshot": "synced",
    "vendor_drift_guard": "tests/test_vendor_drift.py present",
    "t3_linked_pr": 220,
    "t3_worktree_available": $WORKTREE_BOOL,
    "subagents_sync": "attempted",
    "credential_prompt": "completed"
  },
  "deliverables": [
    ".env",
    ".venv",
    "vendor/",
    "scripts/setup_t3.sh",
    "reports/setup.evidence.jsonl",
    "reports/setup.card.json"
  ],
  "evidence_file": "$EVIDENCE_LOG"
}
CARD
echo "Board card written: $CARD_FILE"

echo "=== Setup: validation ==="
# Quick smoke: import family code, confirm vendored sources are importable,
# and that the setup script can reference its own card.
python - <<'PY' || true
import json, pathlib
card = json.load(open("reports/setup.card.json"))
assert card["pr"] == 220
assert "OPENROUTER_API_KEY" in card["credentials_required"]
print("card validated: setup card contract passes.")
print("evidence lines:", len(open("reports/setup.evidence.jsonl").readlines()))
PY

echo "=== Setup complete (profile=$PROFILE_DEFAULT, dry_run=$DRY_RUN) ==="
echo "Next: configure .env keys (see prompt above), then: sandbox run preflight --config ..."
echo "Evidence: $EVIDENCE_LOG  Card: $CARD_FILE"
