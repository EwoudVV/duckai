#!/bin/bash
set -e
# usage: DUCKDNS_TOKEN=xxxx bash scripts/duckdns-update.sh duckduckai
# never commit the token. set it in env/cron only. empty ip= autodetects.
DOMAIN="${1:-duckduckai}"
if [ -z "$DUCKDNS_TOKEN" ]; then echo "set DUCKDNS_TOKEN first"; exit 1; fi
IPV4=$(curl -s --max-time 10 https://api.ipify.org 2>/dev/null || true)
IPV6=$(curl -s --max-time 10 https://api64.ipify.org 2>/dev/null || true)
ARGS=""
echo "$IPV4" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' && ARGS="${ARGS}&ip=${IPV4}"
echo "$IPV6" | grep -q ":" && ARGS="${ARGS}&ipv6=${IPV6}"
curl -s --max-time 20 "https://www.duckdns.org/update?domains=${DOMAIN}&token=${DUCKDNS_TOKEN}${ARGS}" | head -c 20
echo ""
