#!/bin/bash
# WSL bootstrap for local-mailroom-sandbox (native Linux: fcntl works there)
set -e
unset VIRTUAL_ENV TMPDIR TEMP TMP
export UV_PROJECT_ENVIRONMENT=/home/gemooslin/sandbox-venv
cd /mnt/c/Users/grant/sandbox-clone
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
uv python install 3.12 2>/dev/null || true
uv venv "$HOME/sandbox-venv" --python 3.12
uv pip install --python "$HOME/sandbox-venv/bin/python" -e .
"$HOME/sandbox-venv/bin/sandbox" --help | head -25
echo WSL_CLI_SMOKE_OK
