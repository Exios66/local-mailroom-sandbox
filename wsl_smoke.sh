#!/bin/bash
cd /mnt/c/Users/grant/sandbox-clone
V="$HOME/sandbox-venv/bin"
echo "===DOCTOR"
"$V/sandbox" doctor 2>&1 | tail -25
echo "===MOCK_PILOT"
"$V/sandbox" pilot --mock 2>&1 | tail -30
