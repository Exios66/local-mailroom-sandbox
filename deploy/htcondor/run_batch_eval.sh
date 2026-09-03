#!/usr/bin/env bash
# run_batch_eval.sh — CHTC/HTCondor job executable (HUB-026).
#
# Runs INSIDE the vLLM container on the execute node:
#   1. unpack the portable conda env (sandbox deps; conda-pack output)
#   2. serve the model in-process on localhost:8000
#   3. wait for /v1/models health
#   4. run the sandbox evals with SANDBOX_PROFILE=vllm-local
#      (base_url localhost:8000/v1 — same shape as a local GPU box)
#   5. leave everything under results/ for HTCondor to transfer back
#
# Requires the two input tarballs (see README.md one-time setup):
#   mailroom-sandbox.tar.gz   — git archive of packages/local-mailroom-sandbox
#   env-mailroom-sandbox.tar.gz — conda-pack of the mailroom-sandbox env
set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen3-8B}"
PORT=8000
mkdir -p results

echo "== unpack portable env =="
if [ ! -f env-mailroom-sandbox.tar.gz ]; then
    echo "FATAL: env-mailroom-sandbox.tar.gz not transferred" >&2
    exit 1
fi
mkdir -p env
tar -xzf env-mailroom-sandbox.tar.gz -C env
# conda-pack requires activating from the unpacked prefix
source env/bin/activate
echo "python: $(command -v python)"

echo "== unpack sandbox package =="
tar -xzf mailroom-sandbox.tar.gz
cd mailroom-sandbox

echo "== install sandbox into env (light deps; torch/vLLM come from the container) =="
VLLM_DOJO_PIN="${SANDBOX_DOJO_PIN:-v0.12.2}"
pip install --no-deps "llm-dojo-scoring @ git+https://github.com/Exios66/llm-dojo-scoring.git@${VLLM_DOJO_PIN}"
pip install --no-deps -e .
# light runtime deps the container lacks
pip install pyyaml python-dotenv httpx structlog pydantic

echo "== serve vLLM in-process =="
vllm serve "$MODEL" --host 0.0.0.0 --port "$PORT" --max-model-len 8192 \
    > results/vllm_serve.log 2>&1 &
VLLM_PID=$!
trap 'kill "$VLLM_PID" 2>/dev/null || true' EXIT

echo "== wait for /v1/models =="
for _ in $(seq 1 120); do
    if curl -sf "http://localhost:${PORT}/v1/models" > /dev/null; then
        echo "vLLM healthy"
        break
    fi
    if ! kill -0 "$VLLM_PID" 2> /dev/null; then
        echo "FATAL: vLLM exited during startup" >&2
        tail -50 results/vllm_serve.log >&2
        exit 1
    fi
    sleep 10
done

export SANDBOX_PROFILE=vllm-local
export DEFAULT_PROVIDER=vllm
export VLLM_BASE_URL="http://localhost:${PORT}/v1"
# the container's key requirement is satisfied by absence (no VLLM_API_KEY)

echo "== offline fixture prep (no network) =="
python -m mailroom_sandbox.cli --profile vllm-local datasets prepare || true

echo "== evals =="
python -m mailroom_sandbox.cli --profile vllm-local eval sorter --local --dry-run || true
python -m mailroom_sandbox.cli --profile vllm-local eval sorter --local
python -m mailroom_sandbox.cli --profile vllm-local eval extract --local || true

echo "== collect =="
cp -r reports results/ 2> /dev/null || true
echo "done: $(ls results)"
