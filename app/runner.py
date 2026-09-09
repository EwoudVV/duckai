"""Background worker: queued -> reviewing -> waiting-approval -> running -> done.
RUNNER_MODE=docker (prod, needs docker + nvidia runtime) or subprocess (dev, runs python directly, still timeout+no-network optional).
Each job gets ./artifacts/<id>/ with code.py, requirements.txt, run.yaml, stdout.log.
Network: offline=docker --network none. proxied=bridge + HTTP_PROXY to squid + no direct bypass (host firewall does the real block).
"""
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import db
from .review import review

ART = Path("./artifacts")
ART.mkdir(parents=True, exist_ok=True)

BASE_IMAGE = os.environ.get("RUNNER_BASE_IMAGE", "python:3.11-slim")
SQUID_URL = os.environ.get("SQUID_URL", "http://squid:3128")
ALLOW_OPEN = os.environ.get("NET_ALLOW_OPEN", "false").lower() == "true"
DEFAULT_MIN = int(os.environ.get("MAX_MINUTES_DEFAULT", "120"))

_running = False

def job_dir(jid):
    d = ART / str(jid)
    d.mkdir(parents=True, exist_ok=True)
    return d

def _read_code(d: Path) -> str:
    return (d / "code.py").read_text(errors="replace") if (d / "code.py").exists() else ""

def _parse_run_yaml(d: Path) -> dict:
    # tiny yaml subset: key: value lines only, no deps
    out = {}
    p = d / "run.yaml"
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        if ":" in line and not line.strip().startswith("#"):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip("'\"")
    return out

def process_one(jid) -> bool:
    job = db.get_job(jid)
    if not job or job["status"] not in ("queued",):
        return False
    d = job_dir(jid)
    code = _read_code(d)
    if not code.strip():
        db.set_job(jid, status="failed", review="empty submission", ended=time.time())
        return True
    db.set_job(jid, status="reviewing")
    cfg = _parse_run_yaml(d)
    net = (cfg.get("net") or job["net"] or "proxied").lower()
    if net not in ("offline", "proxied", "open"):
        net = "proxied"
    if net == "open" and not ALLOW_OPEN:
        net = "proxied"
    db.set_job(jid, net=net)
    score, reasons = review(code, net)
    db.set_job(jid, score=score, review="\n".join(reasons)[:2000])
    if score >= 70:
        db.set_job(jid, status="rejected", ended=time.time())
        (d / "stdout.log").write_text("REJECTED by review:\n" + "\n".join(reasons))
        return True
    # trusted-ish: auto-approve low scores, hold medium for admin
    auto = int(os.environ.get("REVIEW_AUTO_APPROVE_BELOW", "30"))
    if score >= auto:
        db.set_job(jid, status="waiting-approval")
        return True
    return run_job(jid)

def run_job(jid) -> bool:
    job = db.get_job(jid)
    if not job:
        return False
    d = job_dir(jid)
    cfg = _parse_run_yaml(d)
    minutes = int(cfg.get("minutes_limit", DEFAULT_MIN))
    entry = cfg.get("entry", "main.py")
    args = cfg.get("args", "")
    # normalize: web form stores as code.py; allow entry alias
    if entry != "code.py" and (d / entry).exists():
        shutil.copy(d / entry, d / "code.py")
    mode = os.environ.get("RUNNER_MODE", "docker")
    db.set_job(jid, status="running", started=time.time())
    logf = d / "stdout.log"
    try:
        if mode == "docker":
            _run_docker(jid, d, job, minutes, args, logf)
        else:
            _run_subprocess(jid, d, job, minutes, args, logf)
    except Exception as e:
        with open(logf, "a") as f:
            f.write(f"\n[runner error] {e}\n")
        db.set_job(jid, status="failed", exit_code=125, ended=time.time())
        return True
    return True

def _docker_cmd(jid, d: Path, job: dict, minutes: int, args: str):
    net = job["net"]
    mem = os.environ.get("JOB_MEMORY", "12g")
    cpus = os.environ.get("JOB_CPUS", "4")
    name = f"duckai-{jid}"
    inner = f"pip install -q -r /w/requirements.txt 2>&1 | tail -5; python /w/code.py {args} 2>&1"
    # offline: no network at all, no pip. proxied: bridge + proxy env (squid logs).
    cmd = ["docker", "run", "--rm", "--name", name,
           "--memory", mem, "--cpus", cpus, "--pids-limit", "512",
           "--security-opt", "no-new-privileges:true",
           "--gpus", "all",
           "-v", f"{d.resolve()}:/w:ro",
           "-v", f"{d.resolve()}:/out:rw",
           "-w", "/w"]
    if net == "offline":
        cmd += ["--network", "none"]
    else:
        cmd += ["-e", f"HTTP_PROXY={SQUID_URL}", "-e", f"HTTPS_PROXY={SQUID_URL}",
                "-e", "NO_PROXY=localhost,127.0.0.1",
                "-e", f"DUCKAI_USER={job['user']}", "-e", f"DUCKAI_JOB={jid}"]
    cmd += [BASE_IMAGE, "bash", "-c", inner]
    return cmd, minutes * 60

def _run_docker(jid, d, job, minutes, args, logf):
    cmd, timeout = _docker_cmd(jid, d, job, minutes, args)
    start = time.time()
    with open(logf, "w") as f:
        f.write(f"$ {' '.join(cmd)}\n[net={job['net']} user={job['user']}]\n\n")
    proc = subprocess.Popen(cmd, stdout=open(logf, "a"), stderr=subprocess.STDOUT)
    try:
        proc.wait(timeout=timeout)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        with open(logf, "a") as f:
            f.write(f"\n[TIME LIMIT {minutes}min]\n")
        code = 124
    mins = max(1, int((time.time() - start) / 60))
    db.add_usage(job["user"], mins)
    # truncate giant logs
    if logf.stat().st_size > 2_000_000:
        txt = logf.read_text(errors="replace")[-2_000_000:]
        logf.write_text("...[truncated]...\n" + txt)
    db.set_job(jid, status="done" if code == 0 else "failed", exit_code=code, ended=time.time())

def _run_subprocess(jid, d, job, minutes, args, logf):
    # dev fallback: runs locally with timeout. Still honors offline by stripping proxy env.
    env = dict(os.environ)
    if job["net"] == "offline":
        env.pop("HTTP_PROXY", None); env.pop("HTTPS_PROXY", None)
        env.pop("http_proxy", None); env.pop("https_proxy", None)
    else:
        env["HTTP_PROXY"] = SQUID_URL; env["HTTPS_PROXY"] = SQUID_URL
    start = time.time()
    with open(logf, "w") as f:
        f.write(f"[dev-run net={job['net']} user={job['user']}]\n\n")
    try:
        p = subprocess.run(["python3", "code.py"] + args.split(),
                           cwd=d, capture_output=True, text=True,
                           timeout=minutes * 60, env=env)
        with open(logf, "a") as f:
            f.write(p.stdout[-500_000:] + p.stderr[-500_000:])
        code = p.returncode
    except subprocess.TimeoutExpired as e:
        with open(logf, "a") as f:
            f.write((e.stdout or "") + (e.stderr or "") + f"\n[TIME LIMIT {minutes}min]\n")
        code = 124
    mins = max(1, int((time.time() - start) / 60))
    db.add_usage(job["user"], mins)
    db.set_job(jid, status="done" if code == 0 else "failed", exit_code=code, ended=time.time())

def loop():
    global _running
    if _running:
        return
    _running = True
    while True:
        try:
            jobs = db.list_jobs(50)
            # run oldest queued first
            for j in sorted([x for x in jobs if x["status"] == "queued"], key=lambda x: x["id"]):
                # one running job per user, one GPU => one running total for MVP
                if db.running_for_user(j["user"]) >= int(os.environ.get("MAX_JOBS_PER_USER_RUNNING", "1")):
                    continue
                if any(x["status"] == "running" for x in db.list_jobs(20)):
                    break
                process_one(j["id"])
        except Exception:
            pass
        time.sleep(3)

def start():
    t = threading.Thread(target=loop, daemon=True)
    t.start()
