"""app/routers/auth.py — /api/login, /api/pin-login, /api/set-my-pin,
/api/clear-my-pin, /api/logout, /api/auth-status, /api/my-permissions,
/api/setup-admin. Moved verbatim from main.py (zero logic changes, still
raw sqlite3 via app.core.get_conn)."""
import secrets
from fastapi import APIRouter, HTTPException, Body, Request

from app.core import (
    get_conn, hash_pw, _new_token_entry, _effective_permissions,
    any_user_exists, _current_user_info, TOKENS, ALL_PERMISSIONS,
    LOGIN_ATTEMPTS, LOGIN_LOCKOUT_SECONDS, LOGIN_MAX_ATTEMPTS,
)

router = APIRouter(tags=["auth"])

@router.post("/api/login")
def login(data: dict = Body(...)):
    import time
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    state = LOGIN_ATTEMPTS.get(username, {"count": 0, "locked_until": None})
    now = time.time()
    if state["locked_until"] and now < state["locked_until"]:
        wait_min = max(1, int((state["locked_until"] - now) / 60) + 1)
        raise HTTPException(429, f"Too many failed sign-in attempts. Try again in about {wait_min} minute(s).")

    conn = get_conn()
    row = conn.execute("SELECT salt, pwhash, role FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()

    ok = bool(row and hash_pw(password, row["salt"]) == row["pwhash"])
    if not ok:
        state["count"] += 1
        if state["count"] >= LOGIN_MAX_ATTEMPTS:
            state["locked_until"] = now + LOGIN_LOCKOUT_SECONDS
            state["count"] = 0
        LOGIN_ATTEMPTS[username] = state
        raise HTTPException(401, "Invalid username or password")

    LOGIN_ATTEMPTS.pop(username, None)
    role = row["role"] or "admin"
    token = secrets.token_urlsafe(32)
    TOKENS[token] = _new_token_entry(username, role)
    return {"ok": True, "token": token, "username": username, "role": role,
            "permissions": _effective_permissions(username, role)}


# ---- PIN sign-in: a quick 4-digit alternative to the full password ----
PIN_ATTEMPTS = {}   # username -> {"count": int, "locked_until": epoch_seconds or None}
PIN_LOCKOUT_SECONDS = 5 * 60
PIN_MAX_ATTEMPTS = 5

@router.post("/api/pin-login")
def pin_login(data: dict = Body(...)):
    import time
    username = (data.get("username") or "").strip()
    pin = (data.get("pin") or "").strip()

    state = PIN_ATTEMPTS.get(username, {"count": 0, "locked_until": None})
    now = time.time()
    if state["locked_until"] and now < state["locked_until"]:
        wait_min = max(1, int((state["locked_until"] - now) / 60) + 1)
        raise HTTPException(429, f"Too many wrong PIN attempts. Try again in about {wait_min} minute(s), or sign in with the password instead.")

    conn = get_conn()
    row = conn.execute("SELECT pin_salt, pin_hash, role FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()

    ok = bool(row and row["pin_hash"] and hash_pw(pin, row["pin_salt"]) == row["pin_hash"])
    if not ok:
        state["count"] += 1
        if state["count"] >= PIN_MAX_ATTEMPTS:
            state["locked_until"] = now + PIN_LOCKOUT_SECONDS
            state["count"] = 0
        PIN_ATTEMPTS[username] = state
        if not row or not row["pin_hash"]:
            raise HTTPException(401, "No PIN is set for this account. Sign in with the password instead.")
        raise HTTPException(401, "Incorrect PIN")

    PIN_ATTEMPTS.pop(username, None)
    role = row["role"] or "admin"
    token = secrets.token_urlsafe(32)
    TOKENS[token] = _new_token_entry(username, role)
    return {"ok": True, "token": token, "username": username, "role": role,
            "permissions": _effective_permissions(username, role)}


@router.post("/api/set-my-pin")
def set_my_pin(data: dict = Body(...), request: Request = None):
    token = request.headers.get("authorization", "").replace("Bearer ", "").strip()
    info = TOKENS.get(token)
    if not info:
        raise HTTPException(401, "Not authenticated")
    pin = (data.get("pin") or "").strip()
    if not (pin.isdigit() and len(pin) == 4):
        raise HTTPException(400, "PIN must be exactly 4 digits")
    salt = secrets.token_bytes(16)
    pin_hash = hash_pw(pin, salt)
    conn = get_conn()
    conn.execute("UPDATE users SET pin_salt = ?, pin_hash = ? WHERE username = ?",
                 (salt, pin_hash, info["username"]))
    conn.commit(); conn.close()
    return {"ok": True}


@router.post("/api/clear-my-pin")
def clear_my_pin(request: Request):
    token = request.headers.get("authorization", "").replace("Bearer ", "").strip()
    info = TOKENS.get(token)
    if not info:
        raise HTTPException(401, "Not authenticated")
    conn = get_conn()
    conn.execute("UPDATE users SET pin_salt = NULL, pin_hash = NULL WHERE username = ?", (info["username"],))
    conn.commit(); conn.close()
    return {"ok": True}


@router.post("/api/logout")
def logout(request: Request):
    token = request.headers.get("authorization", "").replace("Bearer ", "").strip()
    TOKENS.pop(token, None)
    return {"ok": True}


@router.get("/api/auth-status")
def auth_status():
    return {"has_account": any_user_exists()}


@router.get("/api/my-permissions")
def my_permissions(request: Request):
    """
    What the currently signed-in user is allowed to do — used by the
    frontend to hide/disable buttons for features they don't have, not just
    block the request after the fact.
    """
    info = _current_user_info(request)
    if not info:
        raise HTTPException(401, "Not authenticated")
    return {"role": info["role"], "permissions": _effective_permissions(info["username"], info["role"])}


@router.post("/api/setup-admin")
def setup_admin(data: dict = Body(...)):
    """
    Create the FIRST account — the Super Admin — from the app itself.
    Only works once: if any account already exists, this is refused (use the
    Manage Users panel, signed in as Super Admin, to add more accounts).
    """
    if any_user_exists():
        raise HTTPException(400, "An account already exists. Sign in, or ask the Super Admin to add you as a user.")
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username:
        raise HTTPException(400, "Username is required")
    if len(password) < 4:
        raise HTTPException(400, "Password must be at least 4 characters")

    salt = secrets.token_bytes(16)
    pwhash = hash_pw(password, salt)
    conn = get_conn()
    conn.execute(
        "INSERT INTO users (username, salt, pwhash, role) VALUES (?, ?, ?, 'super_admin')",
        (username, salt, pwhash))
    conn.commit(); conn.close()

    token = secrets.token_urlsafe(32)
    TOKENS[token] = _new_token_entry(username, "super_admin")
    return {"ok": True, "token": token, "username": username, "role": "super_admin",
            "permissions": list(ALL_PERMISSIONS)}
