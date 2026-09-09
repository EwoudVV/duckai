# duckai

Shared homelab AI + compute for a few trusted people. One gaming PC, one GPU, no nonsense.

You don't get SSH. You submit code, it gets reviewed (heuristic + local AI), it runs sandboxed with logged internet, you watch logs + GPU stats in the browser.

Simple on purpose: FastAPI + SQLite + Docker + vanilla HTML/CSS. No auth provider, no k8s, no framework slop. Fits on a Proxmox VM with GPU passthrough.

## How it works, in user eyes

1. Admin gives you a token + Tailscale access. No public internet.
2. You open `http://duckai:8000`, paste code or link a branch, pick `offline` / `proxied` network, hit Submit.
3. Pipeline: `queued -> reviewing -> waiting-approval -> queued -> running -> done/failed/rejected`
4. You watch live logs, GPU util, queue position. Artifacts (logs, checkpoints, pngs) kept 7 days. Workspace wiped after.
5. Inference stays separate: Ollama + Open WebUI, same tokens.

## Network modes (you pick per job)

- `offline` (`--network none`): zero egress. Cannot phone home, cannot get an abuse letter from this job. Use for torch training on pre-cached models/datasets.
- `proxied` (default): container has no direct 80/443. Only `HTTP_PROXY=http://squid:3128` works. Squid allowlists + logs every domain per job/user. SMTP/SSH/Tor blocked at host firewall. General-purpose (`pip install`, `hf download`) but residual risk remains: someone *can* tunnel bad stuff over allowed HTTPS if they really want to. Logs tie it to a user so you can ban.
- `open`: direct internet. Don't use unless you accept the risk. Disabled by default, admin-only flag.

There is no zero-risk compute with internet. If you need zero risk, use `offline`. See `docs/THREATMODEL.md`.

## Quickstart (on the Proxmox VM host)

```bash
# 1. host prep (docker + nvidia toolkit + firewall + squid net)
sudo bash scripts/install.sh
sudo bash scripts/firewall.sh

# 2. configure
cp .env.example .env
# edit: ADMIN_TOKEN, USER_TOKENS, OLLAMA_URL, NET_DEFAULT=proxied

# 3. run
docker compose up --build -d
# open http://<tailscale-ip>:8000, enter your token
```

Local dev without GPU/docker:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ADMIN_TOKEN=admin USER_TOKENS=alice,bob RUNNER_MODE=subprocess uvicorn app.main:app --reload
```

## Repo layout

```
app/main.py    routes + UI wiring
app/db.py      sqlite (jobs, tokens, usage)
app/auth.py    bearer/cookie tokens, admin vs user
app/review.py  heuristic + Ollama review, score + reasons
app/runner.py  background worker: docker/subprocess, timeouts, log capture
app/stats.py   nvidia-smi poll, queue counts, per-user usage
templates/     vanilla jinja pages (base, index, submit, job, stats)
static/style.css  one stylesheet, system fonts, 720px max-width
runner/base.Dockerfile  baked torch+cuda base for jobs
squid/squid.conf  allowlist + per-job logging
scripts/install.sh firewall.sh  host setup
docs/THREATMODEL.md OPERATIONS.md
```

## Job submission

Web form or API:

```bash
curl -H "Authorization: Bearer alice-token" -F "code=@main.py" \
  -F "requirements=@requirements.txt" -F "net=proxied" -F "title=my-run" \
  http://duckai:8000/api/jobs
```

`run.yaml` (optional, in upload or repo):
```yaml
entry: main.py
args: --epochs 2
minutes_limit: 120
memory: 12g
cpus: 4
dataset: cifar10  # must be pre-cached for offline
```

## Rules (shown on site)

- invite-only, everything logged: code, domains hit, GPU-minutes, by user
- no SMTP, no port scanning, no mining, no hosting phishing/malware
- 1 running job each, 2h default limit, workspace wiped
- break it -> token revoked, job killed, snapshot restore

## License

MIT.
