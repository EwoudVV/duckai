"""duckai web: dashboard, submit, job view, stats, tiny JSON API."""
import json
import os
import re
import time
import urllib.request
from pathlib import Path
from fastapi import FastAPI, Request, Form, UploadFile, File, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db
from .auth import require_user, token_names, token_map
from .runner import start as runner_start, job_dir, run_job
from .stats import gpu

app = FastAPI(title="duckai")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.middleware("http")
async def track(req: Request, call_next):
    resp = await call_next(req)
    try:
        if not req.url.path.startswith("/static"):
            ident = require_user(req)
            if ident:
                if not ident["admin"]:
                    db.touch_user(ident["user"])
                # any valid visit (?token= link, header, form) refreshes the
                # persistent cookie, so login survives reloads until logout
                if req.cookies.get("duckai_token", "") != ident["token"]:
                    resp.set_cookie("duckai_token", ident["token"], httponly=True,
                                    samesite="lax", max_age=31536000, path="/")
    except Exception:
        pass
    return resp

@app.on_event("startup")
def _startup():
    db.init()
    Path("./artifacts").mkdir(parents=True, exist_ok=True)
    # crash/restart recovery: reviewing/running at shutdown never finished
    with db.conn() as c:
        c.execute("UPDATE jobs SET status='queued' WHERE status IN ('reviewing','running')")
    runner_start()

def ident_or_login(req: Request, tmpl: str):
    ident = require_user(req)
    if not ident and tmpl != "login":
        return None
    return ident

def can_see(ident, job):
    return ident["admin"] or job["user"] == ident["user"]

def visible_jobs(ident, limit=100):
    jobs = db.list_jobs(limit)
    if ident["admin"]:
        return jobs
    return [j for j in jobs if j["user"] == ident["user"]]

@app.get("/", response_class=HTMLResponse)
def index(req: Request):
    ident = require_user(req)
    if not ident:
        return templates.TemplateResponse(req, "login.html", {})
    jobs = visible_jobs(ident, 50)
    return templates.TemplateResponse(req, "index.html", {
        "me": ident, "jobs": jobs,
        "queue": db.queue_depth(), "gpu": gpu(),
        "net_default": os.environ.get("NET_DEFAULT", "proxied"),
    })

@app.post("/login")
def login(token: str = Form("")):
    r = RedirectResponse("/", status_code=303)
    r.set_cookie("duckai_token", token.strip(), httponly=True, samesite="lax",
                 max_age=31536000, path="/")
    return r

@app.get("/logout")
def logout():
    r = RedirectResponse("/", status_code=303)
    r.delete_cookie("duckai_token")
    return r

@app.get("/submit", response_class=HTMLResponse)
def submit_page(req: Request):
    ident = require_user(req)
    if not ident:
        return RedirectResponse("/")
    return templates.TemplateResponse(req, "submit.html", {"me": ident})

def save_submission(jid, code_text, code_file, requirements, runyaml, command=""):
    d = job_dir(jid)
    if code_file is not None and getattr(code_file, "filename", ""):
        data = code_file.file.read().decode(errors="replace")
        (d / "code.py").write_text(data[:500_000])
    else:
        (d / "code.py").write_text((code_text or "")[:500_000])
    (d / "requirements.txt").write_text((requirements or "")[:20_000])
    ry = runyaml or ""
    if command and not re.search(r"^command\s*:", ry, re.M):
        ry = ((ry.rstrip() + "\n") if ry.strip() else "") + f"command: {command}\n"
    if ry:
        (d / "run.yaml").write_text(ry[:5_000])

@app.post("/submit")
def submit(req: Request, title: str = Form("untitled"), net: str = Form("proxied"),
           code: str = Form(""), requirements: str = Form(""), runyaml: str = Form(""),
           command: str = Form("python code.py"),
           codefile: UploadFile = File(None)):
    ident = require_user(req)
    if not ident:
        return RedirectResponse("/")
    net = net if net in ("offline", "proxied", "open") else "proxied"
    jid = db.create_job(title[:80] or "untitled", ident["user"], net)
    save_submission(jid, code, codefile, requirements, runyaml or f"net: {net}\n", command[:500])
    return RedirectResponse(f"/job/{jid}?token={ident['token']}", status_code=303)

@app.get("/job/{jid}", response_class=HTMLResponse)
def job_page(req: Request, jid: int):
    ident = require_user(req)
    if not ident:
        return RedirectResponse("/")
    job = db.get_job(jid)
    if not job or not can_see(ident, job):
        return PlainTextResponse("no such job", status_code=404)
    d = job_dir(jid)
    log = (d / "stdout.log").read_text(errors="replace")[-30_000:] if (d / "stdout.log").exists() else "(no logs yet)"
    code = (d / "code.py").read_text(errors="replace")[:30_000] if (d / "code.py").exists() else ""
    return templates.TemplateResponse(req, "job.html", {"me": ident, "job": job, "log": log, "code": code})

@app.get("/job/{jid}/log")
def job_log(req: Request, jid: int):
    ident = require_user(req)
    if not ident:
        return JSONResponse({"err": "auth"}, status_code=401)
    job = db.get_job(jid)
    if not job or not can_see(ident, job):
        return JSONResponse({"err": "not found"}, status_code=404)
    d = job_dir(jid)
    p = d / "stdout.log"
    return PlainTextResponse(p.read_text(errors="replace")[-100_000:] if p.exists() else "(no logs yet)")

@app.post("/job/{jid}/approve")
def approve(req: Request, jid: int, next: str = Form("/")):
    ident = require_user(req)
    if not ident or not ident["admin"]:
        return PlainTextResponse("admin only", status_code=403)
    job = db.get_job(jid)
    if job and job["status"] in ("waiting-approval", "rejected"):
        db.set_job(jid, status="approved")
        # local loop or remote gpu worker picks up `approved`
    if not next.startswith("/") or next.startswith("//"):
        next = f"/job/{jid}"
    return RedirectResponse(next, status_code=303)

@app.post("/job/{jid}/reject")
def reject(req: Request, jid: int, next: str = Form("/")):
    ident = require_user(req)
    if not ident or not ident["admin"]:
        return PlainTextResponse("admin only", status_code=403)
    job = db.get_job(jid)
    if job and job["status"] in ("queued", "reviewing", "waiting-approval", "approved", "running"):
        if job["status"] == "running":
            import subprocess
            subprocess.run(["docker", "rm", "-f", f"duckai-{jid}"], capture_output=True)
        db.set_job(jid, status="rejected", ended=time.time(),
                   review=((job["review"] or "") + "\nrejected by admin")[:2000])
    if not next.startswith("/") or next.startswith("//"):
        next = f"/job/{jid}"
    return RedirectResponse(next, status_code=303)

@app.post("/job/{jid}/kill")
def kill(req: Request, jid: int, next: str = Form("/")):
    ident = require_user(req)
    if not ident or not ident["admin"]:
        return PlainTextResponse("admin only", status_code=403)
    import subprocess
    subprocess.run(["docker", "rm", "-f", f"duckai-{jid}"], capture_output=True)
    db.set_job(jid, status="failed", review="killed by admin", ended=time.time())
    if not next.startswith("/") or next.startswith("//"):
        next = f"/job/{jid}"
    return RedirectResponse(next, status_code=303)

@app.get("/review", response_class=HTMLResponse)
def review_stream(req: Request):
    ident = require_user(req)
    if not ident or not ident["admin"]:
        return PlainTextResponse("admin only", status_code=403)
    return templates.TemplateResponse(req, "review.html", {"me": ident, "jobs": db.list_jobs(30)})

@app.get("/review/rows", response_class=HTMLResponse)
def review_rows(req: Request):
    ident = require_user(req)
    if not ident or not ident["admin"]:
        return PlainTextResponse("admin only", status_code=403)
    return templates.TemplateResponse(req, "_review_rows.html", {"jobs": db.list_jobs(30)})

@app.get("/stats", response_class=HTMLResponse)
def stats_page(req: Request):
    ident = require_user(req)
    if not ident:
        return RedirectResponse("/")
    return templates.TemplateResponse(req, "stats.html", {
        "me": ident, "gpu": gpu(),
        "usage": [u for u in db.usage_all() if u["last_seen"]],
        "queue": db.queue_depth(),
    })

def ago(ts, now):
    if not ts:
        return "never"
    d = int(now - ts)
    if d < 60:
        return "just now"
    if d < 3600:
        return f"{d // 60}m ago"
    if d < 86400:
        return f"{d // 3600}h ago"
    return f"{d // 86400}d ago"

@app.get("/admin", response_class=HTMLResponse)
def admin_page(req: Request):
    ident = require_user(req)
    if not ident or not ident["admin"]:
        return PlainTextResponse("admin only", status_code=403)
    for n in token_names():
        db.ensure_user(n)
    rows = {r["user"]: r for r in db.user_rows()}
    counts = db.job_counts()
    tm = token_map()
    now = time.time()
    users = []
    for n in token_names():
        r = rows.get(n, {"label": "", "last_seen": 0, "gpu_minutes": 0, "jobs_run": 0})
        jc = counts.get(n, {})
        users.append({"name": n, "token": tm.get(n, ""), "label": r["label"], "seen": ago(r["last_seen"], now),
                      "gpu": r["gpu_minutes"], "runs": r["jobs_run"],
                      "jobs": sum(jc.values()), "detail": ", ".join(f"{k}:{v}" for k, v in sorted(jc.items())) or "-"})
    return templates.TemplateResponse(req, "admin.html", {"me": ident, "users": users})

@app.post("/admin/label")
def admin_label(req: Request, user: str = Form(""), label: str = Form("")):
    ident = require_user(req)
    if not ident or not ident["admin"]:
        return PlainTextResponse("admin only", status_code=403)
    if user in token_names():
        db.set_label(user, label)
    return RedirectResponse("/admin", status_code=303)

# --- JSON API (same tokens) ---
@app.get("/api/jobs")
def api_jobs(req: Request):
    ident = require_user(req)
    if not ident:
        return JSONResponse({"err": "auth"}, status_code=401)
    return visible_jobs(ident, 100)

@app.post("/api/jobs")
def api_submit(req: Request, title: str = Form("untitled"), net: str = Form("proxied"),
               code: str = Form(""), requirements: str = Form(""), runyaml: str = Form(""),
               command: str = Form("python code.py"),
               codefile: UploadFile = File(None)):
    ident = require_user(req)
    if not ident:
        return JSONResponse({"err": "auth"}, status_code=401)
    net = net if net in ("offline", "proxied", "open") else "proxied"
    jid = db.create_job(title[:80] or "untitled", ident["user"], net)
    save_submission(jid, code, codefile, requirements, runyaml or f"net: {net}\n", command[:500])
    return {"id": jid, "url": f"/job/{jid}"}

@app.get("/api/job/{jid}")
def api_job(req: Request, jid: int):
    ident = require_user(req)
    if not ident:
        return JSONResponse({"err": "auth"}, status_code=401)
    job = db.get_job(jid)
    if not job or not can_see(ident, job):
        return JSONResponse({"err": "not found"}, status_code=404)
    return job

def is_worker(req: Request):
    t = req.headers.get("authorization", "")
    tok = t[7:].strip() if t.lower().startswith("bearer ") else req.query_params.get("token", "")
    wt = os.environ.get("WORKER_TOKEN", "")
    return bool(wt) and tok == wt

@app.get("/api/worker/next")
def worker_next(req: Request):
    if not is_worker(req):
        return JSONResponse({"err": "auth"}, status_code=401)
    for j in sorted(db.list_jobs(50), key=lambda x: x["id"]):
        if j["status"] == "approved":
            db.set_job(j["id"], status="running", started=time.time())
            return db.get_job(j["id"])
    return {"none": True}

@app.get("/api/worker/job/{jid}/status")
def worker_status(req: Request, jid: int):
    if not is_worker(req):
        return JSONResponse({"err": "auth"}, status_code=401)
    job = db.get_job(jid)
    if not job:
        return JSONResponse({"err": "not found"}, status_code=404)
    return {"status": job["status"]}

@app.get("/api/worker/job/{jid}/files")
def worker_files(req: Request, jid: int):
    if not is_worker(req):
        return JSONResponse({"err": "auth"}, status_code=401)
    from .runner import job_dir
    d = job_dir(jid)
    out = {}
    for name in ("code.py", "requirements.txt", "run.yaml"):
        p = d / name
        out[name] = p.read_text(errors="replace")[:500_000] if p.exists() else ""
    job = db.get_job(jid)
    return {"job": job, "files": out}

@app.post("/api/worker/job/{jid}/result")
async def worker_result(req: Request, jid: int):
    if not is_worker(req):
        return JSONResponse({"err": "auth"}, status_code=401)
    body = await req.json()
    log = (body.get("log") or "")[-2_000_000:]
    from .runner import job_dir
    d = job_dir(jid)
    (d / "stdout.log").write_text(log)
    job = db.get_job(jid)
    if job:
        mins = body.get("minutes", 1)
        try:
            db.add_usage(job["user"], int(mins))
        except Exception:
            pass
        db.set_job(jid, status=body.get("status", "done"),
                   exit_code=int(body.get("exit_code", 0)), ended=time.time())
    return {"ok": True}
