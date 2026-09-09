"""Invite-token auth. ADMIN_TOKEN full access, USER_TOKENS comma list.
Entries are `name:secret` (preferred) or legacy plain `name` (dev only:
token `name` or `name-token` works). Token via Authorization: Bearer <t>,
?token=, or cookie duckai_token."""
import os
from fastapi import Request

def admin_token():
    return os.environ.get("ADMIN_TOKEN", "admin")

def user_tokens():
    raw = os.environ.get("USER_TOKENS", "")
    return [t.strip() for t in raw.split(",") if t.strip()]

def extract_token(req: Request) -> str:
    auth = req.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    q = req.query_params.get("token", "")
    if q:
        return q.strip()
    c = req.cookies.get("duckai_token", "")
    return c.strip()

def identity(req: Request):
    t = extract_token(req)
    if not t:
        return None
    if t == admin_token():
        return {"user": "admin", "admin": True, "token": t}
    for entry in user_tokens():
        if ":" in entry:
            name, secret = entry.split(":", 1)
            name, secret = name.strip(), secret.strip()
            # token IS the full "name:secret" string (secret-only also accepted)
            if t == entry.strip() or t == secret:
                return {"user": name, "admin": False, "token": t}
        elif t == entry or t == f"{entry}-token":
            return {"user": entry, "admin": False, "token": t}
    return None

def require_user(req: Request):
    ident = identity(req)
    return ident
