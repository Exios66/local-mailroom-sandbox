#!/bin/bash
set -euo pipefail
SRC=/mnt/c/Users/grant/sandbox-clone/data
DST=$HOME/sandbox-data
mkdir -p "$DST"
for item in mailroom.db checkpoints.db pipeline runtime handoff labels manifests memory warehouse archive; do
  if [ -e "$SRC/$item" ]; then
    cp -a "$SRC/$item" "$DST/"
    echo "copied $item"
  fi
done
# bashrc export (idempotent)
grep -q MAILROOM_BASE_DIR "$HOME/.bashrc" || echo 'export MAILROOM_BASE_DIR=$HOME/sandbox-data' >> "$HOME/.bashrc"
# repo .env line (idempotent, CRLF-safe append)
ENV=$SRC/../.env
grep -q MAILROOM_BASE_DIR "$ENV" || printf 'MAILROOM_BASE_DIR=/home/gemooslin/sandbox-data\r\n' >> "$ENV"
# wipe the failed run's state on BOTH sides so preflight re-locks fresh onto ext4
rm -rf "$DST/runtime/runs/pipeline-lmstudio-even100"
rm -rf "$SRC/runtime/runs/pipeline-lmstudio-even100"
du -sh "$DST"
ls "$DST"
echo DONE
