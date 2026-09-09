"""duckai web: dashboard, submit, job view, stats, tiny JSON API."""
import os
import time
from pathlib import Path
from fastapi import FastAPI, Request, Form, UploadFile, File, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db
from .auth import require_user
from .runner import start as runner_start, job_dir, run_job
from .stats import gpu

app = FastAPI(title="duckai")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.on_event("startup")
def _startup():
    db.init()
    Path("./artifacts").mkdir(parents=True, exist_ok=True)
    runner_start()

def ident_or_login(req: Request, tmpl: str):
    ident = require_user(req)
    if not ident and tmpl != "login":
        return None
    return ident

@app.get("/", response_class=HTMLResponse)
def index(req: Request):
    ident = require_user(req)
    if not ident:
        return templates.TemplateResponse(req, "login.html", {})
    jobs = db.list_jobs(50)
    return templates.TemplateResponse(req, "index.html", {
        "me": ident, "jobs": jobs,
        "queue": db.queue_depth(), "gpu": gpu(),
        "net_default": os.environ.get("NET_DEFAULT", "proxied"),
    })

@app.post("/login")
def login(token: str = Form("")):
    r = RedirectResponse("/", status_code=303)
    r.set_cookie("duckai_token", token.strip(), httponly=True, samesite="lax")
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

def save_submission(jid, code_text, code_file, requirements, runyaml):
    d = job_dir(jid)
    if code_file is not None and getattr(code_file, "filename", ""):
        data = code_file.file.read().decode(errors="replace")
        (d / "code.py").write_text(data[:500_000])
    else:
        (d / "code.py").write_text((code_text or "")[:500_000])
    (d / "requirements.txt").write_text((requirements or "")[:20_000])
    if runyaml:
        (d / "run.yaml").write_text(runyaml[:5_000])

@app.post("/submit")
def submit(req: Request, title: str = Form("untitled"), net: str = Form("proxied"),
           code: str = Form(""), requirements: str = Form(""), runyaml: str = Form(""),
           codefile: UploadFile = File(None)):
    ident = require_user(req)
    if not ident:
        return RedirectResponse("/")
    net = net if net in ("offline", "proxied", "open") else "proxied"
    jid = db.create_job(title[:80] or "untitled", ident["user"], net)
    save_submission(jid, code, codefile, requirements, runyaml or f"net: {net}\n")
    return RedirectResponse(f"/job/{jid}?token={ident['token']}", status_code=303)

@app.get("/job/{jid}", response_class=HTMLResponse)
def job_page(req: Request, jid: int):
    ident = require_user(req)
    if not ident:
        return RedirectResponse("/")
    job = db.get_job(jid)
    if not job:
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
    d = job_dir(jid)
    p = d / "stdout.log"
    return PlainTextResponse(p.read_text(errors="replace")[-100_000:] if p.exists() else "(no logs yet)")

@app.post("/job/{jid}/approve")
def approve(req: Request, jid: int):
    ident = require_user(req)
    if not ident or not ident["admin"]:
        return PlainTextResponse("admin only", status_code=403)
    job = db.get_job(jid)
    if job and job["status"] == "waiting-approval":
        db.set_job(jid, status="queued")
        # runner loop picks it up; fast-path:
        import threading
        threading.Thread(target=run_job, args=(jid,), daemon=True).start()
    return RedirectResponse(f"/job/{jid}?token={ident['token']}", status_code=303)

@app.post("/job/{jid}/kill")
def kill(req: Request, jid: int):
    ident = require_user(req)
    if not ident or not ident["admin"]:
        return PlainTextResponse("admin only", status_code=403)
    import subprocess
    subprocess.run(["docker", "rm", "-f", f"duckai-{jid}"], capture_output=True)
    db.set_job(jid, status="failed", review="killed by admin", ended=time.time())
    return RedirectResponse(f"/job/{jid}?token={ident['token']}", status_code=303)

@app.get("/stats", response_class=HTMLResponse)
def stats_page(req: Request):
    ident = require_user(req)
    if not ident:
        return RedirectResponse("/")
    return templates.TemplateResponse(req, "stats.html", {
        "me": ident, "gpu": gpu(),
        "usage": db.usage_all(), "queue": db.queue_depth(),
    })

# --- JSON API (same tokens) ---
@app.get("/api/jobs")
def api_jobs(req: Request):
    if not require_user(req):
        return JSONResponse({"err": "auth"}, status_code=401)
    return db.list_jobs(100)

@app.post("/api/jobs")
def api_submit(req: Request, title: str = Form("untitled"), net: str = Form("proxied"),
               code: str = Form(""), requirements: str = Form(""), runyaml: str = Form(""),
               codefile: UploadFile = File(None)):
    ident = require_user(req)
    if not ident:
        return JSONResponse({"err": "auth"}, status_code=401)
    net = net if net in ("offline", "proxied", "open") else "proxied"
    jid = db.create_job(title[:80] or "untitled", ident["user"], net)
    save_submission(jid, code, codefile, requirements, runyaml or f"net: {net}\n")
    return {"id": jid, "url": f"/job/{jid}"}

@app.get("/api/job/{jid}")
def api_job(req: Request, jid: int):
    if not require_user(req):
        return JSONResponse({"err": "auth"}, status_code=401)
    job = db.get_job(jid)
    return job or JSONResponse({"err": "not found"}, status_code=404)
