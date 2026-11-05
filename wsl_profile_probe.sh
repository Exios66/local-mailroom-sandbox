#!/bin/bash
cd /mnt/c/Users/grant/sandbox-clone
V="$HOME/sandbox-venv/bin"
echo "=== CUTOVER (agent->model assignment under lmstudio profile)"
"$V/sandbox" --profile lmstudio cutover 2>&1 | head -25
echo "=== HEALTH probe (offline) under lmstudio"
"$V/sandbox" --profile lmstudio doctor 2>&1 | grep -E "provider|generic|1234|FAIL|WARN" | head -8
