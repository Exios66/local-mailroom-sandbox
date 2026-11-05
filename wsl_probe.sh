#!/bin/bash
# probe reachability of Windows LM Studio server from WSL
GW=$(ip route | awk '/default/ {print $3}')
echo "gateway=$GW"
for H in "127.0.0.1" "$GW" "host.docker.internal"; do
  CODE=$(curl -s -o /tmp/probe.json -w "%{http_code}" --max-time 4 "http://$H:1234/v1/models")
  echo "$H -> $CODE $(head -c 80 /tmp/probe.json 2>/dev/null)"
done
grep -i "networkingMode" /mnt/c/Users/grant/.wslconfig 2>/dev/null || echo "no .wslconfig networkingMode key"
