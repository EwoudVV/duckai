#!/usr/bin/env python3
"""Runs on the GPU box. Polls nest web for queued jobs, runs them in docker, posts logs back.
Env: WEB_BASE_URL=https://duckduckai.duckdns.org WORKER_TOKEN=... SQUID_URL=... RUNNER_BASE_IMAGE=...
No inbound ports needed at home, only outbound polling."""
import os, time, subprocess, tempfile, urllib.request, urllib.parse, json
from pathlib import Path

WEB = os.environ.get("WEB_BASE_URL", "http://localhost:8000").rstrip("/")
TOK = os.environ.get("WORKER_TOKEN", "")
BASE = os.environ.get("RUNNER_BASE_IMAGE", "python:3.11-slim")
SQUID = os.environ.get("SQUID_URL", "http://localhost:3128")

def api(path, data=None, method="GET"):
    req = urllib.request.Request(WEB + path, method=method,
        headers={"Authorization": f"Bearer {TOK}", "Content-Type": "application/json"})
    body = json.dumps(data).encode() if data is not None else None
    with urllib.request.urlopen(req, data=body, timeout=30) as r:
        return json.loads(r.read().decode() or "{}")

def run_one(job):
    jid = job["id"]
    print(f"job {jid} {job['title']} net={job['net']}", flush=True)
    files = api(f"/api/worker/job/{jid}/files")["files"]
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "code.py").write_text(files.get("code.py", ""))
        (d / "requirements.txt").write_text(files.get("requirements.txt", ""))
        net = job.get("net", "proxied")
        cmd = ["docker", "run", "--rm", "--memory", "12g", "--cpus", "4",
               "--pids-limit", "512", "--security-opt", "no-new-privileges:true",
               "--gpus", "all", "-v", f"{d}:/w:ro", "-w", "/w"]
        if net == "offline":
            cmd += ["--network", "none"]
        else:
            cmd += ["-e", f"HTTP_PROXY={SQUID}", "-e", f"HTTPS_PROXY={SQUID}"]
        cmd += [BASE, "bash", "-c", "pip install -q -r /w/requirements.txt 2>&1 | tail -3; python /w/code.py 2>&1"]
        start = time.time()
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=2 * 3600)
            log, code = (p.stdout + p.stderr)[-500_000:], p.returncode
        except subprocess.TimeoutExpired as e:
            log, code = ((e.stdout or "") + (e.stderr or "") + "\n[TIME LIMIT]\n")[-500_000:], 124
        mins = max(1, int((time.time() - start) / 60))
        api(f"/api/worker/job/{jid}/result", {"log": log, "exit_code": code,
            "status": "done" if code == 0 else "failed", "minutes": mins}, method="POST")
        print(f"job {jid} finished exit={code}", flush=True)

if not TOK:
    raise SystemExit("set WORKER_TOKEN")
print(f"polling {WEB} ...", flush=True)
while True:
    try:
        nxt = api("/api/worker/next")
        if nxt.get("none"):
            time.sleep(5)
        else:
            run_one(nxt)
    except Exception as e:
        print("poll err:", e, flush=True)
        time.sleep(10)
