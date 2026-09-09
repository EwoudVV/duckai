"""Invite-token auth. ADMIN_TOKEN full access, USER_TOKENS comma list.
Token via Authorization: Bearer <t> or ?token= or cookie duckai_token."""
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
    # USER_TOKENS entries are usernames AND tokens for MVP (alice's token is "alice-token"
    # or just "alice" in dev). Accept both raw name and name-token forms.
    for u in user_tokens():
        if t == u or t == f"{u}-token":
            return {"user": u, "admin": False, "token": t}
    return None

def require_user(req: Request):
    ident = identity(req)
    return ident
