#!/bin/bash
set -e
# usage: DUCKDNS_TOKEN=xxxx bash scripts/duckdns-update.sh duckduckai
# never commit the token. set it in env/cron only.
DOMAIN="${1:-duckduckai}"
if [ -z "$DUCKDNS_TOKEN" ]; then echo "set DUCKDNS_TOKEN first"; exit 1; fi
curl -s "https://www.duckdns.org/update?domains=${DOMAIN}&token=${DUCKDNS_TOKEN}&ip=" | head -c 20
echo ""
