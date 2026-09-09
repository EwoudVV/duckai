"""SQLite store. Tables: jobs, usage. Tokens come from env, not db (4 users)."""
import os
import sqlite3
import time
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "duckai.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  user TEXT NOT NULL,
  net TEXT NOT NULL DEFAULT 'proxied',
  status TEXT NOT NULL DEFAULT 'queued',
  score INTEGER DEFAULT 0,
  review TEXT DEFAULT '',
  log_path TEXT DEFAULT '',
  created REAL NOT NULL,
  started REAL DEFAULT 0,
  ended REAL DEFAULT 0,
  exit_code INTEGER DEFAULT NULL,
  gpu_peak_mb INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS usage (
  user TEXT PRIMARY KEY,
  gpu_minutes INTEGER DEFAULT 0,
  jobs_run INTEGER DEFAULT 0
);
"""

def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init():
    with conn() as c:
        c.executescript(SCHEMA)

def create_job(title, user, net):
    now = time.time()
    with conn() as c:
        cur = c.execute(
            "INSERT INTO jobs (title, user, net, status, created) VALUES (?,?,?,?,?)",
            (title, user, net, "queued", now),
        )
        c.execute(
            "INSERT OR IGNORE INTO usage (user, gpu_minutes, jobs_run) VALUES (?,?,0)",
            (user, 0),
        )
        return cur.lastrowid

def get_job(jid):
    with conn() as c:
        r = c.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        return dict(r) if r else None

def list_jobs(limit=100):
    with conn() as c:
        rows = c.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

def set_job(jid, **kv):
    keys = ", ".join(f"{k}=?" for k in kv)
    with conn() as c:
        c.execute(f"UPDATE jobs SET {keys} WHERE id=?", (*kv.values(), jid))

def queue_depth():
    with conn() as c:
        r = c.execute(
            "SELECT COUNT(*) n FROM jobs WHERE status IN ('queued','waiting-approval','approved','reviewing','running')"
        ).fetchone()
        return r["n"]

def running_for_user(user):
    with conn() as c:
        r = c.execute(
            "SELECT COUNT(*) n FROM jobs WHERE user=? AND status='running'", (user,)
        ).fetchone()
        return r["n"]

def add_usage(user, minutes, ran=1):
    with conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO usage (user, gpu_minutes, jobs_run) VALUES (?,?,0)",
            (user, 0),
        )
        c.execute(
            "UPDATE usage SET gpu_minutes=gpu_minutes+?, jobs_run=jobs_run+? WHERE user=?",
            (minutes, ran, user),
        )

def usage_all():
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM usage ORDER BY gpu_minutes DESC")]
