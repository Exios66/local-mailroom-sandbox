#!/bin/bash
# verify WSL -> Windows LM Studio reachability under mirrored networking
for H in localhost 127.0.0.1 host.docker.internal "$(ip route | awk '/default/ {print $3}')"; do
  C=$(curl -s -o /dev/null -w "%{http_code}" --max-time 4 "http://$H:1234/v1/models")
  echo "$H -> $C"
done
echo ===CUTOVER
cd /mnt/c/Users/grant/sandbox-clone
/home/gemooslin/sandbox-venv/bin/sandbox doctor --live 2>&1 | grep -E "provider|1234|FAIL|ok" | head -6
