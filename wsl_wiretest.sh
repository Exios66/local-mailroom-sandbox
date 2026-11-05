#!/bin/bash
cd /mnt/c/Users/grant/sandbox-clone
export MAILROOM_JSON_MODE=off
/home/gemooslin/sandbox-venv/bin/sandbox pilot --local --sample 5 2>&1 > /mnt/c/Users/grant/AppData/Local/hermes/cache/scratch/pilot_full.json
