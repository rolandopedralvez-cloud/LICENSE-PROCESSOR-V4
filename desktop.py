"""
desktop.py  —  Run the NTC Telco Database as a single desktop window.

Starts the FastAPI server hidden in the background and shows the app in a
native window. Close the window and the server stops with it — no cmd window,
no leftover process.

One-time setup (adds the window library to your venv):
    venv\\Scripts\\activate
    pip install pywebview

Run:  double-click NTC.vbs  (or:  python desktop.py)
"""

import os
import sys
import time
import socket
import threading

HOST = "0.0.0.0"   # listen on the network too, so other PCs can reach this one
LOCAL_UI = "127.0.0.1"   # the desktop window itself always talks to localhost
PORT = 8000


def wait_for_port(host, port, timeout=40):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), 0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def start_server():
    import uvicorn
    from app.main import app  # the restructured FastAPI app (was: import main; main.app)
    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="warning")
    server = uvicorn.Server(config)
    # signal handlers only work on the main thread; disable them for the bg thread
    server.install_signal_handlers = lambda: None
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    return server


def main_entry():
    # always run from this file's folder so it finds telco.db, index.html, etc.
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    try:
        import webview
    except ImportError:
        print("pywebview is not installed. In this folder run:")
        print("    venv\\Scripts\\activate")
        print("    pip install pywebview")
        sys.exit(1)

    start_server()
    if not wait_for_port(LOCAL_UI, PORT, 40):
        print("The server did not start in time.")
        sys.exit(1)

    class Api:
        """Bridge the desktop window can call for things the browser can't do,
        like saving a file through a native Save dialog."""
        def export(self, ids, token=None, all=False):
            import json, urllib.request
            try:
                headers = {"Content-Type": "application/json"}
                if token:
                    headers["Authorization"] = "Bearer " + token
                req = urllib.request.Request(
                    f"http://{LOCAL_UI}:{PORT}/api/export",
                    data=json.dumps({"ids": ids, "all": bool(all)}).encode("utf-8"),
                    headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=120) as resp:
                    content = resp.read()
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    return {"ok": False, "error": "Session expired — please sign in again."}
                return {"ok": False, "error": f"Could not build the file: {e}"}
            except Exception as e:
                return {"ok": False, "error": f"Could not build the file: {e}"}
            try:
                win = webview.windows[0]
                result = win.create_file_dialog(
                    webview.SAVE_DIALOG,
                    save_filename="RSL_export.xlsx",
                    file_types=("Excel files (*.xlsx)", "All files (*.*)"))
            except Exception as e:
                return {"ok": False, "error": f"Save dialog failed: {e}"}
            if not result:
                return {"ok": False, "cancelled": True}
            path = result if isinstance(result, str) else result[0]
            if not path.lower().endswith(".xlsx"):
                path += ".xlsx"
            try:
                with open(path, "wb") as f:
                    f.write(content)
            except Exception as e:
                return {"ok": False, "error": f"Could not save: {e}"}
            return {"ok": True, "path": path}

        def browse_folder(self):
            """Opens a native 'choose a folder' dialog and returns the path
            picked — used by the Backup Settings screen so the person can
            browse to their Google Drive folder instead of typing it."""
            try:
                win = webview.windows[0]
                result = win.create_file_dialog(webview.FOLDER_DIALOG)
            except Exception as e:
                return {"ok": False, "error": f"Folder dialog failed: {e}"}
            if not result:
                return {"ok": False, "cancelled": True}
            path = result if isinstance(result, str) else result[0]
            return {"ok": True, "path": path}

        def export_url(self, path, filename="export.xlsx", token=None):
            """
            General-purpose version of export() — POSTs to any backend path
            (Analytics, Pivot, Pivot-selected, etc.) and saves the result
            through the same native Save dialog, so every export in the app
            behaves the same way: you choose the folder and the filename.
            """
            import urllib.request
            try:
                headers = {}
                if token:
                    headers["Authorization"] = "Bearer " + token
                url = path if path.startswith("http") else f"http://{LOCAL_UI}:{PORT}{path}"
                req = urllib.request.Request(url, data=b"", headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=120) as resp:
                    content = resp.read()
            except urllib.error.HTTPError as e:
                if e.code == 401:
                    return {"ok": False, "error": "Session expired — please sign in again."}
                if e.code == 403:
                    return {"ok": False, "error": "Only the Super Admin can export data."}
                return {"ok": False, "error": f"Could not build the file: {e}"}
            except Exception as e:
                return {"ok": False, "error": f"Could not build the file: {e}"}
            try:
                win = webview.windows[0]
                result = win.create_file_dialog(
                    webview.SAVE_DIALOG,
                    save_filename=filename,
                    file_types=("Excel files (*.xlsx)", "All files (*.*)"))
            except Exception as e:
                return {"ok": False, "error": f"Save dialog failed: {e}"}
            if not result:
                return {"ok": False, "cancelled": True}
            savepath = result if isinstance(result, str) else result[0]
            if not savepath.lower().endswith(".xlsx"):
                savepath += ".xlsx"
            try:
                with open(savepath, "wb") as f:
                    f.write(content)
            except Exception as e:
                return {"ok": False, "error": f"Could not save: {e}"}
            return {"ok": True, "path": savepath}

    webview.create_window(
        "Radio Station Processor",
        f"http://{LOCAL_UI}:{PORT}",
        width=1320, height=860, min_size=(900, 600),
        resizable=True,
        js_api=Api(),
    )
    _start_backup_monitor()
    webview.start()   # blocks here until the window is closed

    # window closed -> clean up and exit the whole process (kills the server too)
    try:
        import print_engine
        print_engine.shutdown()      # close the background Excel, if any
    except Exception:
        pass
    try:
        import print_engine_word
        print_engine_word.shutdown()  # close the background Word, if any
    except Exception:
        pass
    backup_on_close()
    os._exit(0)


# ---------------------------------------------------------------- auto-backup
# EDIT THIS to your actual Google Drive sync folder (see backup_to_gdrive.bat for how
# to find it). Leave as None to skip Google Drive and just back up to a local folder.
GDRIVE_BACKUP_FOLDER = r"G:\My Drive\NTC-Backups"
LOCAL_BACKUP_FOLDER = r"C:\NTC-App-Backups"
BACKUP_CHECK_MINUTES = 10   # how often the background monitor checks for internet


STATUS_FILE = "backup_status.json"


def _write_status(**fields):
    """Record what the backup monitor is doing right now, so the app's UI
    can show a live badge — checking, backing up, no internet, or done."""
    import json, datetime
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, STATUS_FILE)
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
    except Exception:
        pass   # the status badge is a nice-to-have, never worth crashing over


def _has_internet(timeout=3):
    """Quick, reliable check — tries to reach Google's public DNS server.
    Doesn't depend on any particular website being reachable/blocked."""
    import socket
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        return True
    except OSError:
        return False


def _get_gdrive_backup_folder():
    """Read the backup folder from settings.json (set via the app's Users
    screen) if present, otherwise fall back to the constant below."""
    import json
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "settings.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            v = data.get("gdrive_backup_folder")
            if v:
                return v
        except Exception:
            pass
    return GDRIVE_BACKUP_FOLDER


def _get_last_backup_date():
    """Read the date of the last successful backup from the status file."""
    import json
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, STATUS_FILE)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f).get("last_backup")
    except Exception:
        pass
    return None


def _snapshot_sqlite_db(src_path, dest_path):
    """
    Copy the database using SQLite's own backup API instead of a plain file
    copy. This guarantees a clean, consistent snapshot even if a write is
    happening at the exact instant the backup runs — a raw file copy can't
    make that guarantee, but SQLite's backup API is built for exactly this.
    """
    import sqlite3
    src_conn = sqlite3.connect(src_path)
    dest_conn = sqlite3.connect(dest_path)
    try:
        with dest_conn:
            src_conn.backup(dest_conn)
    finally:
        dest_conn.close()
        src_conn.close()


def run_backup_if_needed():
    """
    Copy the whole app folder into ONE fixed backup folder (no date in the
    name), updating it in place — so Google Drive always holds a single
    current backup instead of a new dated folder piling up every day.
    telco.db is backed up separately via SQLite's own backup API (see
    _snapshot_sqlite_db) for a guaranteed-consistent copy, rather than a
    plain file copy.
    Still runs at most once per day; runs quietly and never raises.
    Returns True if a backup actually ran, False if skipped.
    """
    import shutil
    import datetime

    try:
        here = os.path.dirname(os.path.abspath(__file__))
        today = datetime.date.today().strftime("%Y-%m-%d")

        if _get_last_backup_date() == today:
            _write_status(state="done", last_backup=today)
            return False   # already backed up today — skip

        gdrive_folder = _get_gdrive_backup_folder()
        dest_root = gdrive_folder if os.path.isdir(os.path.dirname(gdrive_folder) or "C:\\") else LOCAL_BACKUP_FOLDER
        dest = os.path.join(dest_root, "NTC-App-Backup")   # single fixed folder, always the same one

        _write_status(state="backing_up")
        os.makedirs(dest_root, exist_ok=True)
        shutil.copytree(
            here, dest, dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("venv", "__pycache__", "*.pyc", "telco.db"),
        )
        src_db = os.path.join(here, "telco.db")
        if os.path.exists(src_db):
            _snapshot_sqlite_db(src_db, os.path.join(dest, "telco.db"))
        print(f"Backup updated: {dest}")
        _write_status(state="done", last_backup=today, last_backup_path=dest)
        return True
    except Exception as e:
        # never let a backup problem stop the app
        print(f"(Backup skipped — {e})")
        _write_status(state="error", last_error=str(e))
        return False


def backup_on_close():
    """Kept for the shutdown path — one last attempt as the app closes."""
    run_backup_if_needed()


def _backup_monitor_loop():
    """
    Runs the whole time the app is open. Every few minutes, checks whether
    today's backup is still missing — and if internet is available right
    now, runs it immediately, rather than waiting for you to close the app.
    This matters if your connection is intermittent: the moment it comes
    back, the backup happens on its own.
    """
    import time
    while True:
        try:
            _write_status(state="checking")
            if _has_internet():
                run_backup_if_needed()
            else:
                _write_status(state="no_internet")
        except Exception:
            pass
        time.sleep(BACKUP_CHECK_MINUTES * 60)


def _start_backup_monitor():
    t = threading.Thread(target=_backup_monitor_loop, daemon=True)
    t.start()



if __name__ == "__main__":
    main_entry()
