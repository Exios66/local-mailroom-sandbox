#!/bin/bash
# Reproduce the 400: what does LM Studio reject now that json_object was tolerated before?
BODY_J='{"model":"qwen3.5-9b","messages":[{"role":"user","content":"Return only json: {\"ok\": true}"}],"temperature":0,"max_tokens":200,"response_format":{"type":"json_object"}}'
BODY_T='{"model":"qwen3.5-9b","messages":[{"role":"user","content":"Return only json: {\"ok\": true}"}],"temperature":0,"max_tokens":200}'
echo "== WITH response_format json_object:"
curl -s --max-time 120 http://localhost:1234/v1/chat/completions -H "Content-Type: application/json" -d "$BODY_J" | head -c 500
echo; echo "== PLAIN (no response_format):"
curl -s --max-time 120 http://localhost:1234/v1/chat/completions -H "Content-Type: application/json" -d "$BODY_T" | head -c 500
echo; echo "== FULL ERROR BODY (json_object, verbose):"
curl -s --max-time 120 -w "\nHTTP %{http_code}\n" http://localhost:1234/v1/chat/completions -H "Content-Type: application/json" -d "$BODY_J" | tail -c 600
