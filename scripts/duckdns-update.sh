#!/bin/bash
set -e
# usage: DUCKDNS_TOKEN=xxxx bash scripts/duckdns-update.sh duckduckai
# never commit the token. set it in env/cron only. empty ip= autodetects.
DOMAIN="${1:-duckduckai}"
if [ -z "$DUCKDNS_TOKEN" ]; then echo "set DUCKDNS_TOKEN first"; exit 1; fi
IPV6=$(curl -s --max-time 10 https://api64.ipify.org 2>/dev/null || true)
if echo "$IPV6" | grep -q ":"; then
  curl -s --max-time 20 "https://www.duckdns.org/update?domains=${DOMAIN}&token=${DUCKDNS_TOKEN}&ipv6=${IPV6}" | head -c 20
else
  curl -s --max-time 20 "https://www.duckdns.org/update?domains=${DOMAIN}&token=${DUCKDNS_TOKEN}&ip=" | head -c 20
fi
echo ""
