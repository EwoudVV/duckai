# duckai

my old gaming pc is turning into a shared gpu box for a few people. im not using it much so might as well let ppl run stuff on it.

site lives on my nest box (always on). the actual gpu runs on my proxmox box at home, which phones home to nest and grabs jobs. so the site stays up even when the gpu box is off or rebooting.

you dont get ssh. you submit code on the site, it gets looked at, then it runs on the gpu box sandboxed. you watch logs on the site.

## how it works

1. i give you a token. site is tailscale or nest domain only, no open signup.
2. you go to the site, paste code or upload a .py, pick offline or proxied, hit submit.
3. it goes `queued -> reviewing -> waiting-approval -> running -> done/failed/rejected`
4. you watch the log live. files it makes stay for 7 days then gone. workspace gets wiped.
5. ollama/openwebui for chat stuff is separate, same token.

## the two boxes

- `nest` (ssh duck@hackclub.app): just the website + queue + logs. no gpu, no docker, nothing heavy. `RUNNER_ENABLED=false` here.
- `gpu box` (proxmox vm at home): runs `scripts/remote-worker.py`, polls nest, runs jobs in docker with the gpu, posts logs back. this is the only place that runs untrusted code.

## net modes (pick per job)

- `offline`: no internet at all in the container. safest. use this for torch training if you already have the model/dataset baked in.
- `proxied`: has to go through squid proxy. it allowlists github/pypi/huggingface/ubuntu and logs every domain per user/job. normal `pip install` and `hf download` work. not zero risk though, someone determined could still tunnel junk over allowed https. thats why everything is logged to a user.
- `open`: direct internet. off by default, dont ask unless you have a reason.

no zero-risk compute with internet, thats just how it is. if you want zero risk use offline.

## running it

on nest (website only):
```bash
git clone https://github.com/EwoudVV/duckai ~/duckai
cd ~/duckai
bash scripts/nest-install.sh
cp .env.example .env
# edit .env: ADMIN_TOKEN, USER_TOKENS, RUNNER_ENABLED=false, WORKER_TOKEN=some-long-random
systemctl --user enable --now duckai
# in nest dashboard -> domains, add your subdomain + custom duckduckai.duckdns.org
```

duckdns updater (on nest, cron, token from env not repo):
```bash
export DUCKDNS_TOKEN=xxxx  # yours from duckdns.org, env only, never in the repo
bash scripts/duckdns-update.sh duckduckai
```

on gpu box (the runner):
```bash
git clone https://github.com/EwoudVV/duckai ~/duckai
cd ~/duckai
sudo bash scripts/install.sh
sudo bash scripts/firewall.sh
cp .env.example .env
# edit .env: WEB_BASE_URL=https://duckduckai.duckdns.org, WORKER_TOKEN=same-as-nest, RUNNER_BASE_IMAGE=duckai-base
python3 scripts/remote-worker.py
```

local laptop dev (dont host here, its not stable):
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
ADMIN_TOKEN=admin USER_TOKENS=alice,bob RUNNER_MODE=subprocess RUNNER_ENABLED=true uvicorn app.main:app --reload
```

## submitting

web form, or:
```bash
curl -H "Authorization: Bearer alice-token" -F "code=@main.py" -F "title=my-run" -F "net=proxied" https://duckduckai.duckdns.org/api/jobs
```

optional `run.yaml` next to your code:
```yaml
entry: main.py
args: --epochs 2
minutes_limit: 120
```

## rules

invite only. i log code, domains hit, logs, gpu minutes, all tied to your name. no expectation of privacy on this box.
no spam, no scanning, no miners, no phishing/malware hosting.
1 running job each, 2h default.
break it and i revoke your token and restore snapshot. dont make me do that.

mit.
