"""app/routers/settings.py — /api/settings, /api/backup-status,
/api/backup/run-now. Moved verbatim from main.py."""
import os
import json
import shutil
import datetime
from fastapi import APIRouter, HTTPException, Body, Request

from app.config import DB
from app.core import (
    get_conn, role_for, require_super_admin, _current_user_info,
    _user_display_prefs, hash_pw,
)

router = APIRouter(tags=["settings"])


# ---------------------------------------------------------------- SETTINGS
# A simple shared file both the app and desktop.py's backup monitor read —
# so changing a setting here takes effect immediately, no code editing needed.
SETTINGS_FILE = "settings.json"
DEFAULT_SETTINGS = {"gdrive_backup_folder": r"G:\My Drive\NTC-Backups"}


def _load_settings():
    import json
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root (was: this script's own folder) -- settings.py moved into app/routers/ during the FastAPI restructuring, but settings.json / backup_status.json / the backed-up app folder itself still live in the project root next to telco.db and start.bat, not next to this .py file
    path = os.path.join(here, SETTINGS_FILE)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = dict(DEFAULT_SETTINGS)
            merged.update(data)
            return merged
        except Exception:
            pass
    return dict(DEFAULT_SETTINGS)


def _save_settings(data):
    import json
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root (was: this script's own folder) -- settings.py moved into app/routers/ during the FastAPI restructuring, but settings.json / backup_status.json / the backed-up app folder itself still live in the project root next to telco.db and start.bat, not next to this .py file
    path = os.path.join(here, SETTINGS_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


@router.get("/api/settings")
def get_settings(request: Request):
    require_super_admin(request)
    return _load_settings()


@router.post("/api/settings")
def update_settings(data: dict = Body(...), request: Request = None):
    require_super_admin(request)
    current = _load_settings()
    if "gdrive_backup_folder" in data:
        current["gdrive_backup_folder"] = str(data["gdrive_backup_folder"]).strip()
    _save_settings(current)
    return {"ok": True, "settings": current}


@router.get("/api/backup-status")
def get_backup_status():
    """
    What the background backup monitor (in desktop.py) is doing right now —
    read by the small status badge in the app header. Available to anyone
    signed in, not just Super Admin, since it's just informational.
    """
    import json
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root (was: this script's own folder) -- settings.py moved into app/routers/ during the FastAPI restructuring, but settings.json / backup_status.json / the backed-up app folder itself still live in the project root next to telco.db and start.bat, not next to this .py file
    path = os.path.join(here, "backup_status.json")
    if not os.path.exists(path):
        return {"state": "unknown"}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"state": "unknown"}


def _write_backup_status(**fields):
    import json, datetime
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root (was: this script's own folder) -- settings.py moved into app/routers/ during the FastAPI restructuring, but settings.json / backup_status.json / the backed-up app folder itself still live in the project root next to telco.db and start.bat, not next to this .py file
    path = os.path.join(here, "backup_status.json")
    data = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    data.update(fields)
    data["updated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


@router.post("/api/backup/run-now")
def run_backup_now(request: Request):
    """
    Manual 'push backup now' — copies the app folder (including telco.db) to
    the same single backup folder the automatic daily backup uses, right
    away, on demand. Doesn't change the automatic schedule at all: today's
    date still gets recorded, so the background monitor simply sees today's
    backup as already done and won't repeat it — nothing about the auto
    backup's timing or behavior is altered by using this button.
    telco.db is snapshotted via SQLite's own backup API (see
    _snapshot_sqlite_db) for a guaranteed-consistent copy, rather than a
    plain file copy that could in theory land mid-write.
    """
    require_super_admin(request)
    import shutil, datetime, sqlite3

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # project root (was: this script's own folder) -- settings.py moved into app/routers/ during the FastAPI restructuring, but settings.json / backup_status.json / the backed-up app folder itself still live in the project root next to telco.db and start.bat, not next to this .py file
    today = datetime.date.today().strftime("%Y-%m-%d")
    settings = _load_settings()
    gdrive_folder = settings.get("gdrive_backup_folder") or DEFAULT_SETTINGS["gdrive_backup_folder"]
    local_fallback = r"C:\NTC-App-Backups"
    dest_root = gdrive_folder if os.path.isdir(os.path.dirname(gdrive_folder) or "C:\\") else local_fallback
    dest = os.path.join(dest_root, "NTC-App-Backup")   # same single fixed folder as the auto backup

    try:
        _write_backup_status(state="backing_up")
        os.makedirs(dest_root, exist_ok=True)
        shutil.copytree(
            here, dest, dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("venv", "__pycache__", "*.pyc", "telco.db"),
        )
        src_db = os.path.join(here, "telco.db")
        if os.path.exists(src_db):
            src_conn = sqlite3.connect(src_db)
            dest_conn = sqlite3.connect(os.path.join(dest, "telco.db"))
            try:
                with dest_conn:
                    src_conn.backup(dest_conn)
            finally:
                dest_conn.close(); src_conn.close()
        _write_backup_status(state="done", last_backup=today, last_backup_path=dest)
        return {"ok": True, "path": dest}
    except Exception as e:
        _write_backup_status(state="error", last_error=str(e))
        raise HTTPException(500, f"Backup failed: {e}")


# ---------------------------------------------------------------- ACCOUNT PREFERENCES
# Personal, per-account display preferences -- available to EVERY signed-in
# user (not just Super Admin, unlike the Backup section above). Theme/font
# only ever affect how the app looks in that person's own browser; nothing
# server-side reads or depends on them.
VALID_THEMES = {"light", "dark"}
VALID_FONTS = {"sans", "serif", "mono"}
VALID_SIZES = {"sm", "md", "lg", "xl"}

@router.get("/api/my-preferences")
def get_my_preferences(request: Request):
    info = _current_user_info(request)
    if not info:
        raise HTTPException(401, "Not authenticated")
    prefs = _user_display_prefs(info["username"])
    prefs["username"] = info["username"]
    return prefs


@router.put("/api/my-preferences")
def update_my_preferences(data: dict = Body(...), request: Request = None):
    info = _current_user_info(request)
    if not info:
        raise HTTPException(401, "Not authenticated")
    sets, params = [], []
    if "theme" in data:
        theme = str(data["theme"]).strip()
        if theme not in VALID_THEMES:
            raise HTTPException(400, f"theme must be one of {sorted(VALID_THEMES)}")
        sets.append("theme = ?"); params.append(theme)
    if "font_family" in data:
        font_family = str(data["font_family"]).strip()
        if font_family not in VALID_FONTS:
            raise HTTPException(400, f"font_family must be one of {sorted(VALID_FONTS)}")
        sets.append("font_family = ?"); params.append(font_family)
    if "font_size" in data:
        font_size = str(data["font_size"]).strip()
        if font_size not in VALID_SIZES:
            raise HTTPException(400, f"font_size must be one of {sorted(VALID_SIZES)}")
        sets.append("font_size = ?"); params.append(font_size)
    if "display_name" in data:
        sets.append("display_name = ?"); params.append((str(data["display_name"]).strip() or None))
    if not sets:
        raise HTTPException(400, "No valid preference fields supplied")
    params.append(info["username"])
    conn = get_conn()
    conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE username = ?", params)
    conn.commit(); conn.close()
    prefs = _user_display_prefs(info["username"])
    prefs["username"] = info["username"]
    return {"ok": True, **prefs}


# Cap comfortably above what a client-side-resized (e.g. 200x200) JPEG/PNG
# needs as a base64 data: URI, while still keeping telco.db (which this is
# stored in, see ensure_schema in app/core.py) from bloating if someone
# tries to upload something huge -- the resize is expected to happen in the
# browser before this is ever called; this is just a server-side backstop.
MAX_AVATAR_DATA_URI_LEN = 400_000

@router.post("/api/my-avatar")
def update_my_avatar(data: dict = Body(...), request: Request = None):
    info = _current_user_info(request)
    if not info:
        raise HTTPException(401, "Not authenticated")
    avatar_data = data.get("data")
    if avatar_data is not None:
        if not isinstance(avatar_data, str) or not avatar_data.startswith("data:image/"):
            raise HTTPException(400, "avatar must be a data:image/... URI")
        if len(avatar_data) > MAX_AVATAR_DATA_URI_LEN:
            raise HTTPException(400, "Image is too large — please use a smaller picture")
    conn = get_conn()
    conn.execute("UPDATE users SET avatar_data = ? WHERE username = ?", (avatar_data, info["username"]))
    conn.commit(); conn.close()
    return {"ok": True}


@router.post("/api/my-password")
def change_my_password(data: dict = Body(...), request: Request = None):
    """Self-service password change -- separate from Manage Users' admin
    reset (app/routers/users.py), which doesn't require knowing the old
    password. Same 8-character floor as every other password path in the
    app (see app/routers/auth.py's setup_admin)."""
    info = _current_user_info(request)
    if not info:
        raise HTTPException(401, "Not authenticated")
    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""
    if len(new_password) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")
    conn = get_conn()
    row = conn.execute("SELECT salt, pwhash FROM users WHERE username = ?", (info["username"],)).fetchone()
    if not row or hash_pw(current_password, row["salt"]) != row["pwhash"]:
        conn.close()
        raise HTTPException(401, "Current password is incorrect")
    import secrets
    new_salt = secrets.token_bytes(16)
    new_hash = hash_pw(new_password, new_salt)
    conn.execute("UPDATE users SET salt = ?, pwhash = ? WHERE username = ?", (new_salt, new_hash, info["username"]))
    conn.commit(); conn.close()
    return {"ok": True}
