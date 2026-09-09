#!/bin/bash
set -e
# nest box = website only. no docker, no gpu. just python + systemd user service.
cd "$(dirname "$0")/.."
sudo apt-get update && sudo apt-get install -y python3 python3-venv curl 2>/dev/null || apt-get update && apt-get install -y python3 python3-venv curl || true
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
mkdir -p data artifacts data/squid-logs
cp -n .env.example .env || true
echo "edit .env first: ADMIN_TOKEN, USER_TOKENS, WORKER_TOKEN, RUNNER_ENABLED=false"
echo "then: systemctl --user enable --now duckai  (or copy duckai.service to ~/.config/systemd/user/)"
