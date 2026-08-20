"""
print_engine.py  —  Fast preview/print by keeping Excel open in the background.

The first preview starts Excel and opens PRINT_ready.xlsx once (a few seconds).
Every preview/print after that reuses the same Excel + workbook, so it's nearly
instant. All Excel work runs on one dedicated thread (the safe way to reuse a
COM object across web requests) and recovers automatically if you close Excel.
"""

import os
import threading
import queue
from app.legacy import print_stage

PRINT_FILE = "PRINT_ready.xlsx"
SHEETS_TO_PRINT = ["FRONT"]   # one page only


class _Job:
    def __init__(self, lic_id, mode):
        self.lic_id = lic_id
        self.mode = mode
        self.done = threading.Event()
        self.ok = False
        self.error = None


def _get_pid_from_hwnd(hwnd):
    """Turn a window handle into the process ID that owns it — lets us
    target exactly the Excel instance this code started, nothing else."""
    try:
        import win32process
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return pid
    except Exception:
        return None


def _pid_is_running(pid):
    if not pid:
        return False
    try:
        import win32api
        import win32con
        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION, False, pid)
        if handle:
            win32api.CloseHandle(handle)
            return True
    except Exception:
        return False
    return False


def force_close_if_stuck(pid, wait_seconds=3):
    """
    Last-resort safety net: if the specific Excel process we started is
    STILL running a few seconds after we asked it to quit nicely, force it
    closed. Only ever targets that exact process ID — never a blanket
    'close all Excel' — so it can't touch an Excel window you opened
    yourself for something unrelated.
    """
    import time
    if not pid:
        return
    time.sleep(wait_seconds)
    if _pid_is_running(pid):
        try:
            os.system(f"taskkill /F /PID {pid} >nul 2>&1")
        except Exception:
            pass


class _PrinterService(threading.Thread):
    """Owns one Excel instance on its own thread and processes print jobs."""
    def __init__(self, db_path, here):
        super().__init__(daemon=True)
        self.db_path = db_path
        self.here = here
        self.q = queue.Queue()
        self.excel = None
        self.wb = None
        self.excel_pid = None   # the exact process this service started —
                                 # used as a last-resort safety net on shutdown

    def submit(self, lic_id, mode, timeout=180):
        job = _Job(lic_id, mode)
        self.q.put(job)
        if not job.done.wait(timeout=timeout):
            raise RuntimeError("Print timed out")
        if job.error:
            raise job.error
        return job.ok

    def stop(self):
        self.q.put(None)

    # ---- runs on the dedicated thread ----
    def run(self):
        import pythoncom
        import win32com.client as win32
        pythoncom.CoInitialize()
        try:
            while True:
                job = self.q.get()
                if job is None:
                    break
                try:
                    self._process(job, win32)
                except Exception as e:      # noqa
                    job.error = e
                finally:
                    if not job.done.is_set():
                        job.done.set()
        finally:
            try:
                if self.excel is not None:
                    # suppress any "Save changes?" prompt — without this, Excel
                    # can hang waiting for an answer nobody's there to give,
                    # leaving EXCEL.EXE running as an orphaned process even
                    # after the app has closed
                    self.excel.DisplayAlerts = False
                    # close EVERY open workbook, not just the one we were
                    # tracking, so nothing is left in a "modified" state that
                    # could block Quit()
                    try:
                        for w in list(self.excel.Workbooks):
                            try:
                                w.Saved = True
                                w.Close(SaveChanges=False)
                            except Exception:
                                pass
                    except Exception:
                        pass
                    self.excel.Quit()
            except Exception:
                pass
            pythoncom.CoUninitialize()

    def _alive(self):
        if self.excel is None or self.wb is None:
            return False
        try:
            _ = self.wb.Name          # touch it; throws if closed
            return True
        except Exception:
            return False

    def _ensure(self, win32):
        if self._alive():
            return self.wb
        # (re)start Excel and open the workbook
        print_path = os.path.join(self.here, PRINT_FILE)
        try:
            os.remove(print_path + ":Zone.Identifier")   # unblock if downloaded
        except OSError:
            pass
        self.excel = win32.Dispatch("Excel.Application")
        self.excel.Visible = True
        self.excel.DisplayAlerts = False
        self.excel_pid = _get_pid_from_hwnd(self.excel.Hwnd)
        self.wb = self.excel.Workbooks.Open(print_path, UpdateLinks=0)
        return self.wb

    def _process(self, job, win32):
        rec = print_stage.fetch_record(self.db_path, job.lic_id)
        if not rec:
            job.ok = False
            job.done.set()
            return
        wb = self._ensure(win32)
        stage = wb.Sheets(print_stage.STAGING_SHEET)
        row = print_stage.STAGING_ROW
        stage.Range(f"A{row}:BG{row}").ClearContents()
        for col, value in print_stage.staging_cells(rec):
            stage.Cells(row, col).Value = value
        self.excel.CalculateFull()

        # Release the web request now — the data is in place. The preview window
        # (which is modal) then opens without making the browser wait for it.
        job.ok = True
        job.done.set()

        for sheet_name in SHEETS_TO_PRINT:
            ws = wb.Sheets(sheet_name)
            try:
                self.excel.Visible = True
                ws.Activate()
            except Exception:
                pass
            if job.mode == "open":
                pass          # just show the filled-in workbook — no print/preview
            elif job.mode == "preview":
                ws.PrintPreview()      # blocks this thread until you close it
            else:
                ws.PrintOut()


_service = None
_lock = threading.Lock()


def _get_service(db_path):
    global _service
    with _lock:
        if _service is None or not _service.is_alive():
            here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root (was: this script's own folder) -- these files moved into app/legacy/ during the FastAPI restructuring, but the template/output files (PRINT_ready.xlsx, RSL_Format_2025_mapped.docx, telco.db, etc.) still live in the project root next to start.bat, not next to this .py file
            db_full = db_path if os.path.isabs(db_path) else os.path.join(here, db_path)
            _service = _PrinterService(db_full, here)
            _service.start()
    return _service


def print_one(lic_id, db_path, mode="preview"):
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root (was: this script's own folder) -- these files moved into app/legacy/ during the FastAPI restructuring, but the template/output files (PRINT_ready.xlsx, RSL_Format_2025_mapped.docx, telco.db, etc.) still live in the project root next to start.bat, not next to this .py file
    if not os.path.exists(os.path.join(here, PRINT_FILE)):
        raise FileNotFoundError(f"{PRINT_FILE} not found in {here}")
    try:
        import win32com.client  # noqa  (just to check it's installed)
    except ImportError:
        raise RuntimeError("pywin32 not installed. Run: pip install pywin32")
    return _get_service(db_path).submit(lic_id, mode)


def shutdown():
    """Close the background Excel when the app stops."""
    global _service
    pid = _service.excel_pid if _service is not None else None
    if _service is not None and _service.is_alive():
        _service.stop()
        _service.join(timeout=10)
    _service = None
    # graceful shutdown had 10 seconds to close things down properly above —
    # if Excel is somehow still running after that, this is the hard
    # fallback, targeting only that exact process
    force_close_if_stuck(pid, wait_seconds=1)
