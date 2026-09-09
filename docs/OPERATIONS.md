# Operations

## Host prep (Proxmox VM, Ubuntu 22.04+, 1 GPU via passthrough)

```bash
sudo bash scripts/install.sh   # docker + nvidia container toolkit + net
sudo bash scripts/firewall.sh  # blocks SMTP, job net -> LAN, logs drops
cp .env.example .env && nano .env
docker compose up --build -d
docker compose logs -f app
```

Verify: `curl -H "Authorization: Bearer $ADMIN_TOKEN" localhost:8000/api/jobs`

## Daily

- check `/stats`: queue depth, GPU util, per-user minutes
- approve `waiting-approval` jobs, revoke token if abuse
- `docker system prune -f` weekly, prune `artifacts/` older than 7d (cron included in install.sh)

## Restore when broken

```bash
# app state is sqlite in ./data, jobs logs in ./artifacts
# snapshots are Proxmox-side:
#   Datacenter -> Node -> VM -> Snapshots -> clean-base -> Rollback
docker compose down && docker compose up -d
```

## Adding a user

1. `USER_TOKENS` add name, `docker compose up -d app`
2. Give them Tailscale invite + token + link + rules page
3. First 3 jobs manual approve, then auto-approve if review score < 30

## Pre-caching for offline jobs

Put datasets/models on host, mount read-only into jobs:

```bash
# example: bake into runner/base image or mount
# runner/base.Dockerfile has HF_CACHE pre-pulled tiny models
docker build -t duckai-base -f runner/base.Dockerfile runner/
```

Set `RUNNER_BASE_IMAGE=duckai-base` in `.env`.
