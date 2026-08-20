"""app/routers/settings.py — /api/settings, /api/backup-status,
/api/backup/run-now. Moved verbatim from main.py."""
import os
import json
import shutil
import datetime
from fastapi import APIRouter, HTTPException, Body, Request

from app.config import DB
from app.core import get_conn, role_for, require_super_admin

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
