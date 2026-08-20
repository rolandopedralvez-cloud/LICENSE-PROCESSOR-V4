"""
app/core.py — shared helpers moved verbatim out of the original main.py
(auth/token handling, permission checks, activity log, ensure_schema()).

Zero logic changes from main.py at this stage (step 3 of
MODERNIZATION_PLAN.md) — routers still call these raw-sqlite3 helpers.
ensure_schema() is retired piece by piece as Alembic migrations take over
(see MODERNIZATION_PLAN.md section 3.5).
"""
import sqlite3
import hashlib
from fastapi import HTTPException, Request

from app.config import DB

def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def cols(conn, table):
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]

# columns the client is never allowed to set directly
PROTECTED = {"id", "created_at", "updated_at"}

def clean_payload(conn, table, data: dict):
    """Keep only real, writable columns from the incoming JSON."""
    valid = set(cols(conn, table)) - PROTECTED
    return {k: v for k, v in data.items() if k in valid}

# ---------------------------------------------------------------- login / auth
PBKDF_ROUNDS = 200_000
TOKENS = {}   # token -> {"username":..., "role":..., "created":..., "last_seen":...}
              # (in memory; cleared on restart)

# Sessions expire two ways: if nothing happens for TOKEN_IDLE_TIMEOUT_SECONDS
# (person walked away / left it signed in on a shared PC), or once
# TOKEN_ABSOLUTE_TIMEOUT_SECONDS is reached regardless of activity (so a
# token that leaked somehow doesn't stay valid forever). Both are generous
# for an office tool -- this isn't meant to log anyone out mid-task.
TOKEN_IDLE_TIMEOUT_SECONDS = 4 * 60 * 60       # 4 hours of no activity
TOKEN_ABSOLUTE_TIMEOUT_SECONDS = 16 * 60 * 60  # 16 hours since sign-in, max

def hash_pw(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF_ROUNDS)

def _new_token_entry(username, role):
    import time
    now = time.time()
    return {"username": username, "role": role, "created": now, "last_seen": now}

def _get_token_info(token):
    """Look up a token, evicting it if it's expired. Returns None if the
    token is missing or expired. On success, refreshes last_seen so the
    idle-timeout clock resets on every authenticated request."""
    import time
    info = TOKENS.get(token)
    if not info:
        return None
    now = time.time()
    if now - info.get("created", now) > TOKEN_ABSOLUTE_TIMEOUT_SECONDS:
        TOKENS.pop(token, None)
        return None
    if now - info.get("last_seen", now) > TOKEN_IDLE_TIMEOUT_SECONDS:
        TOKENS.pop(token, None)
        return None
    info["last_seen"] = now
    return info

def role_for(request):
    token = request.headers.get("authorization", "").replace("Bearer ", "").strip()
    info = _get_token_info(token)
    return info["role"] if info else None

def any_user_exists():
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    return n > 0

def ensure_schema():
    """Create/upgrade tables that may be missing."""
    conn = get_conn()
    # region_raw / class_of_station_raw: originally these were only ever
    # added by migrate.py's one-time Excel import (idempotent ALTERs run
    # there, not here) — meaning a database created via create_db.py alone
    # (no migrate.py run yet, e.g. a fresh dev/test DB with no source
    # spreadsheet) is missing them, which breaks anything reading the full
    # `licenses` row shape, including the new SQLAlchemy models in
    # app/models/license.py. Added here too so ensure_schema() alone is
    # enough to produce a complete schema, matching what every
    # already-migrated production telco.db already has.
    if "region_raw" not in cols(conn, "licenses"):
        conn.execute("ALTER TABLE licenses ADD COLUMN region_raw TEXT;")
    if "class_of_station_raw" not in cols(conn, "licenses"):
        conn.execute("ALTER TABLE licenses ADD COLUMN class_of_station_raw TEXT;")
    if "renewed_from" not in cols(conn, "licenses"):
        conn.execute("ALTER TABLE licenses ADD COLUMN renewed_from INTEGER;")
    if "deleted_at" not in cols(conn, "licenses"):
        conn.execute("ALTER TABLE licenses ADD COLUMN deleted_at TEXT;")
    if "import_batch" not in cols(conn, "licenses"):
        # tags which Import run (or manual entry) a record came from, so a
        # whole batch can be found and deleted together later — see
        # /api/import/commit and the Recently Added grouping
        conn.execute("ALTER TABLE licenses ADD COLUMN import_batch TEXT;")
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        salt     BLOB NOT NULL,
        pwhash   BLOB NOT NULL
    );""")
    # add role column if this is an older users table (existing user = master/admin)
    if "role" not in cols(conn, "users"):
        conn.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'admin';")
    # older versions used the role name 'admin' for the top role; normalize it
    # to 'super_admin' so accounts created before this update still get full access
    conn.execute("UPDATE users SET role = 'super_admin' WHERE role = 'admin';")
    # optional 4-digit PIN for quick sign-in, alongside the regular password
    if "pin_salt" not in cols(conn, "users"):
        conn.execute("ALTER TABLE users ADD COLUMN pin_salt BLOB;")
    if "pin_hash" not in cols(conn, "users"):
        conn.execute("ALTER TABLE users ADD COLUMN pin_hash BLOB;")
    # per-user feature checklist for "user"-role accounts (super_admin always
    # has everything regardless of this). Stored as a JSON array of strings.
    if "permissions" not in cols(conn, "users"):
        conn.execute("ALTER TABLE users ADD COLUMN permissions TEXT;")
        # Backfill existing "user" accounts with the permissions that were
        # OPEN to everyone before this update, so nobody's access silently
        # shrinks. Import/Export/Purge were already Super-Admin-only before,
        # so they stay off by default — Super Admin can opt individual users
        # in from Manage Users.
        import json as _json
        default_perms = _json.dumps(["can_delete", "can_batch_renew", "can_location_check"])
        conn.execute("UPDATE users SET permissions = ? WHERE role != 'super_admin' AND permissions IS NULL", (default_perms,))
    # activity log — records who did what to which license, for history tracking
    conn.execute("""CREATE TABLE IF NOT EXISTS activity_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        ts         TEXT NOT NULL,
        username   TEXT,
        action     TEXT NOT NULL,
        license_id INTEGER,
        license_no TEXT,
        detail     TEXT
    );""")
    conn.execute("""CREATE TABLE IF NOT EXISTS schema_meta (
        key TEXT PRIMARY KEY, value TEXT
    );""")
    # persisted import flags — duplicates/conflicts/possible-misspellings found
    # during an Import, kept around after the one-time review popup closes so
    # they can be looked at and cleared later from the Flagged Records view
    conn.execute("""CREATE TABLE IF NOT EXISTS import_flags (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        ts           TEXT NOT NULL,
        username     TEXT,
        status       TEXT NOT NULL,
        license_no   TEXT,
        licensee     TEXT,
        existing_id  INTEGER,
        diff_json    TEXT,
        action_taken TEXT,
        resolved     INTEGER NOT NULL DEFAULT 0,
        resolved_by  TEXT,
        resolved_ts  TEXT,
        ignored      INTEGER NOT NULL DEFAULT 0,
        ignored_by   TEXT,
        ignored_ts   TEXT
    );""")
    if "ignored" not in cols(conn, "import_flags"):
        # older databases created this table before "Ignore" existed
        conn.execute("ALTER TABLE import_flags ADD COLUMN ignored INTEGER NOT NULL DEFAULT 0;")
        conn.execute("ALTER TABLE import_flags ADD COLUMN ignored_by TEXT;")
        conn.execute("ALTER TABLE import_flags ADD COLUMN ignored_ts TEXT;")
    # scanned RSL uploads waiting for a human to check them before anything
    # touches the real database. A scan is read automatically (AI vision) as
    # a starting draft, but nothing from here reaches `licenses` until a
    # person reviews/corrects the draft and explicitly approves it.
    conn.execute("""CREATE TABLE IF NOT EXISTS quarantine_scans (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        ts              TEXT NOT NULL,
        uploaded_by     TEXT,
        filename        TEXT,
        stored_path     TEXT,
        status          TEXT NOT NULL DEFAULT 'pending',
        extracted_json  TEXT,
        corrected_json  TEXT,
        low_confidence  TEXT,
        extract_error   TEXT,
        license_id      INTEGER,
        reviewed_by     TEXT,
        reviewed_ts     TEXT
    );""")
    # v2: New/Save/Save-as-New and Print/Preview/Open File become individually
    # controllable too. They were open to everyone before — grandfather every
    # existing "user" account in so nobody's access silently disappears; the
    # Super Admin can then uncheck them per-person from Manage Users if wanted.
    migrated_v2 = conn.execute("SELECT value FROM schema_meta WHERE key='perms_v2'").fetchone()
    if not migrated_v2:
        import json as _json
        rows = conn.execute("SELECT username, permissions FROM users WHERE role != 'super_admin'").fetchall()
        for r in rows:
            try:
                existing = _json.loads(r["permissions"]) if r["permissions"] else []
            except Exception:
                existing = []
            changed = False
            for p in ("can_create", "can_edit", "can_print"):
                if p not in existing:
                    existing.append(p); changed = True
            if changed:
                conn.execute("UPDATE users SET permissions = ? WHERE username = ?", (_json.dumps(existing), r["username"]))
        conn.execute("INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('perms_v2', '1')")
    conn.commit()
    conn.close()

ensure_schema()

ALL_PERMISSIONS = ["can_create", "can_edit", "can_delete", "can_purge", "can_print",
                    "can_import", "can_export", "can_batch_renew", "can_location_check"]
PERMISSION_LABELS = {
    "can_create":         "Add new records (New / Save as New)",
    "can_edit":           "Save changes (overwrite existing record)",
    "can_delete":         "Delete records (move to Trash)",
    "can_purge":          "Permanently delete (empty Trash / purge)",
    "can_print":          "Print, Print Preview, and Open File",
    "can_import":         "Import records from Excel",
    "can_export":         "Export records to Excel",
    "can_batch_renew":    "Batch Renew",
    "can_location_check": "Location Check tool",
}

def _current_user_info(request):
    token = request.headers.get("authorization", "").replace("Bearer ", "").strip()
    return _get_token_info(token)

def _user_permissions(username):
    import json as _json
    conn = get_conn()
    row = conn.execute("SELECT permissions FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if not row or not row["permissions"]:
        return []
    try:
        return _json.loads(row["permissions"])
    except Exception:
        return []

def require_permission(request, perm):
    """Super Admin always passes. A 'user' account needs this specific
    permission checked in Manage Users, or the action is refused."""
    role = role_for(request)
    if role == "super_admin":
        return
    info = _current_user_info(request)
    if not info:
        raise HTTPException(401, "Not authenticated")
    if perm not in _user_permissions(info["username"]):
        label = PERMISSION_LABELS.get(perm, perm)
        raise HTTPException(403, f"You don't have permission for this ({label}). Ask your Super Admin to enable it for your account.")

def log_activity(request, action, license_id=None, license_no=None, detail=None):
    """Record an entry in the activity log. Never lets a logging problem
    break the actual request — failures here are swallowed silently."""
    import datetime
    try:
        info = _current_user_info(request) if request is not None else None
        username = info["username"] if info else None
        conn = get_conn()
        conn.execute(
            "INSERT INTO activity_log (ts, username, action, license_id, license_no, detail) VALUES (?,?,?,?,?,?)",
            (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), username, action, license_id, license_no, detail),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

def _diff_summary(old_row, new_payload, max_fields=8):
    """Build a short human-readable list of which fields changed and how,
    for the activity log entry on an edit."""
    changes = []
    for k, new_v in new_payload.items():
        if k in PROTECTED:
            continue
        old_v = old_row.get(k) if old_row else None
        old_norm = "" if old_v is None else str(old_v)
        new_norm = "" if new_v is None else str(new_v)
        if old_norm != new_norm:
            old_disp = old_norm if old_norm else "(blank)"
            new_disp = new_norm if new_norm else "(blank)"
            changes.append(f"{k}: '{old_disp}' → '{new_disp}'")
    if not changes:
        return "No field changes"
    shown = changes[:max_fields]
    more = len(changes) - len(shown)
    text = "; ".join(shown)
    if more > 0:
        text += f"; and {more} more field(s)"
    return text


def _effective_permissions(username, role):
    """Super Admin implicitly has every permission; a 'user' account has
    exactly what's been checked for them in Manage Users."""
    if role == "super_admin":
        return list(ALL_PERMISSIONS)
    return _user_permissions(username)


# Password login lockout — same shape as the PIN lockout below, so a
# brute-force attempt against the full password is throttled exactly like
# repeated wrong PINs already are, instead of being allowed unlimited tries.
LOGIN_ATTEMPTS = {}   # username -> {"count": int, "locked_until": epoch_seconds or None}
LOGIN_LOCKOUT_SECONDS = 5 * 60
LOGIN_MAX_ATTEMPTS = 5


def require_super_admin(request: Request):
    if role_for(request) != "super_admin":
        raise HTTPException(403, "Only the Super Admin can manage users")


def _dms_to_dec(deg, mins, secs):
    """Degrees/minutes/seconds -> decimal degrees, or None if unparseable.
    Used by the Location Check tool and pivot exports — moved here from its
    original spot in main.py (was defined mid-file, after location_check()
    but before its own module finished loading; that only worked because
    Python resolves the name at call time, once the whole module is loaded.
    Splitting into separate files means it needs an explicit import instead."""
    try:
        return (float(deg or 0) + float(mins or 0) / 60 + float(secs or 0) / 3600)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- shared cross-router state
# These used to be module-level globals sitting right above the section of
# main.py that used them. Centralized here (rather than left in whichever
# router file happened to come first in the original file) so every router
# that needs them imports from one place instead of reaching into a sibling
# router module.
IMPORT_CACHE = {}   # token -> {"rows": [...], "flags": [...]}  (parsed, awaiting confirm)

SCAN_DIR = "scanned_uploads"
SCAN_MODEL = "claude-sonnet-5"   # good accuracy on scanned/handwritten forms;
                                   # switch to a Haiku model if cost matters
                                   # more than accuracy for your volume
