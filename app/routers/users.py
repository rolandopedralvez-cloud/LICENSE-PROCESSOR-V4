"""app/routers/users.py — /api/users*, /api/permissions-catalog,
/api/activity-log. Moved verbatim from main.py."""
import secrets
import json
from fastapi import APIRouter, HTTPException, Body, Request

from app.core import (
    get_conn, hash_pw, role_for, require_permission, log_activity,
    ALL_PERMISSIONS, PERMISSION_LABELS, require_super_admin, TOKENS,
)

router = APIRouter(tags=["users"])

@router.get("/api/users")
def list_users(request: Request):
    require_super_admin(request)
    import json as _json
    conn = get_conn()
    rows = conn.execute("SELECT username, role, pin_hash, permissions FROM users ORDER BY "
                         "CASE role WHEN 'super_admin' THEN 0 ELSE 1 END, username").fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            perms = _json.loads(r["permissions"]) if r["permissions"] else []
        except Exception:
            perms = []
        out.append({"username": r["username"], "role": r["role"],
                     "has_pin": r["pin_hash"] is not None, "permissions": perms})
    return {"users": out}


@router.get("/api/permissions-catalog")
def permissions_catalog(request: Request):
    """The full list of toggleable permissions, with labels — used to build
    the checklist in Manage Users."""
    require_super_admin(request)
    return {"permissions": [{"key": k, "label": PERMISSION_LABELS[k]} for k in ALL_PERMISSIONS]}


@router.get("/api/activity-log")
def get_activity_log(license_no: str = "", username: str = "", action: str = "", limit: int = 300, request: Request = None):
    """
    History tracking: who did what, and to which record. Super Admin only.
    Optional filters: license_no (partial match), username (exact),
    action (exact: create/edit/delete/restore/purge/import/batch_renew).
    """
    require_super_admin(request)
    where, params = [], []
    if license_no:
        where.append("license_no LIKE ?"); params.append(f"%{license_no}%")
    if username:
        where.append("username = ?"); params.append(username)
    if action:
        where.append("action = ?"); params.append(action)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    conn = get_conn()
    rows = conn.execute(
        f"SELECT id, ts, username, action, license_id, license_no, detail "
        f"FROM activity_log {clause} ORDER BY id DESC LIMIT ?",
        params + [max(1, min(limit, 2000))],
    ).fetchall()
    total = conn.execute(f"SELECT COUNT(*) FROM activity_log {clause}", params).fetchone()[0]
    conn.close()
    return {"count": len(rows), "total": total, "results": [dict(r) for r in rows]}


@router.post("/api/users")
def add_user(data: dict = Body(...), request: Request = None):
    require_super_admin(request)
    import json as _json
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    role = data.get("role") or "user"
    pin = (data.get("pin") or "").strip()   # optional
    perms = data.get("permissions")
    if role not in ("super_admin", "user"):
        role = "user"
    if not username:
        raise HTTPException(400, "Username is required")
    if pin and not (pin.isdigit() and len(pin) == 4):
        raise HTTPException(400, "PIN must be exactly 4 digits (or left blank)")
    perms_json = None
    clean_perms = None
    if perms is not None:
        clean_perms = [p for p in perms if p in ALL_PERMISSIONS]
        perms_json = _json.dumps(clean_perms)

    conn = get_conn()
    existing_row = conn.execute("SELECT role, permissions FROM users WHERE username = ?", (username,)).fetchone()
    exists = existing_row is not None

    # Snapshot the before-state so we can write a clear audit trail entry —
    # who changed what, on an account that can print, delete, and export
    # real licensing records, is exactly the kind of thing that should be
    # traceable later.
    old_role = existing_row["role"] if existing_row else None
    try:
        old_perms = set(_json.loads(existing_row["permissions"])) if existing_row and existing_row["permissions"] else set()
    except Exception:
        old_perms = set()

    if exists:
        # Editing an existing account: password and PIN are each optional —
        # leave either blank to keep it unchanged. Role and permissions
        # always update to whatever was submitted.
        if password and len(password) < 4:
            raise HTTPException(400, "Password must be at least 4 characters (or leave blank to keep it unchanged)")
        sets, params = ["role=?"], [role]
        if perms_json is not None:
            sets += ["permissions=?"]; params += [perms_json]
        pw_changed = False
        pin_changed = False
        if password:
            salt = secrets.token_bytes(16)
            sets += ["salt=?", "pwhash=?"]
            params += [salt, hash_pw(password, salt)]
            pw_changed = True
        if pin:
            pin_salt = secrets.token_bytes(16)
            sets += ["pin_salt=?", "pin_hash=?"]
            params += [pin_salt, hash_pw(pin, pin_salt)]
            pin_changed = True
        params.append(username)
        conn.execute(f"UPDATE users SET {','.join(sets)} WHERE username=?", params)
        action = "updated"

        # A role change takes effect immediately for anyone already signed
        # in, instead of waiting for their next login — otherwise a
        # just-demoted account would keep acting as Super Admin (or a
        # just-promoted one would stay stuck as a limited user) for the
        # rest of that session.
        if old_role != role:
            for tok_info in TOKENS.values():
                if tok_info.get("username") == username:
                    tok_info["role"] = role

        change_bits = []
        if old_role != role:
            change_bits.append(f"role: '{old_role}' -> '{role}'")
        if clean_perms is not None:
            new_perms = set(clean_perms)
            added = sorted(new_perms - old_perms)
            removed = sorted(old_perms - new_perms)
            if added:
                change_bits.append(f"permissions granted: {', '.join(added)}")
            if removed:
                change_bits.append(f"permissions removed: {', '.join(removed)}")
        if pw_changed:
            change_bits.append("password changed")
        if pin_changed:
            change_bits.append("PIN changed")
        detail = f"Account '{username}' updated" + ((" — " + "; ".join(change_bits)) if change_bits else " (no changes)")
        log_activity(request, "user_management", detail=detail)
    else:
        if len(password) < 4:
            conn.close()
            raise HTTPException(400, "Password must be at least 4 characters")
        salt = secrets.token_bytes(16)
        pwhash = hash_pw(password, salt)
        pin_salt = secrets.token_bytes(16) if pin else None
        pin_hash = hash_pw(pin, pin_salt) if pin else None
        conn.execute("INSERT INTO users (username, salt, pwhash, role, pin_salt, pin_hash, permissions) VALUES (?,?,?,?,?,?,?)",
                     (username, salt, pwhash, role, pin_salt, pin_hash, perms_json if perms_json is not None else _json.dumps([])))
        action = "added"
        perm_note = f" with permissions: {', '.join(clean_perms)}" if clean_perms else ""
        log_activity(request, "user_management", detail=f"Account '{username}' created as role '{role}'{perm_note}")
    conn.commit(); conn.close()
    return {"ok": True, "username": username, "role": role, "action": action}


@router.post("/api/users/{username}/clear-pin")
def clear_user_pin(username: str, request: Request):
    require_super_admin(request)
    conn = get_conn()
    cur = conn.execute("UPDATE users SET pin_salt = NULL, pin_hash = NULL WHERE username = ?", (username,))
    conn.commit(); conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "User not found")
    return {"ok": True}


@router.delete("/api/users/{username}")
def remove_user(username: str, request: Request):
    require_super_admin(request)
    me = None
    token = request.headers.get("authorization", "").replace("Bearer ", "").strip()
    info = TOKENS.get(token)
    if info:
        me = info["username"]
    if username == me:
        raise HTTPException(400, "You can't remove your own account while signed in as it")
    conn = get_conn()
    cur = conn.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit(); conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "User not found")
    # invalidate any active sessions for that user
    dead = [t for t, v in TOKENS.items() if v["username"] == username]
    for t in dead: TOKENS.pop(t, None)
    log_activity(request, "user_management", detail=f"Account '{username}' removed")
    return {"ok": True, "removed": username}
