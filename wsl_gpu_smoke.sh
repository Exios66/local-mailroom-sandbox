#!/bin/bash
cd /mnt/c/Users/grant/sandbox-clone
V=/home/gemooslin/sandbox-venv/bin/sandbox
echo "=== DOCTOR LIVE (provider probe)"
$V doctor --live 2>&1 | grep -E "provider|langfuse|FAIL|WARN" | head -6
echo "=== CHAT PROBE (raw, qwen3.5-9b, JSON mode)"
curl -s --max-time 90 http://localhost:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.5-9b","messages":[{"role":"user","content":"Return only JSON: {\"ok\": true}"}],"temperature":0,"max_tokens":50,"response_format":{"type":"json_object"}}' | head -c 400
echo
echo "=== PILOT LOCAL sample 5 (real GPU, $0)"
$V pilot --local --sample 5 2>&1 | tail -45
