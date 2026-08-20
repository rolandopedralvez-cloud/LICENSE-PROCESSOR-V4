"""
print_engine_word.py  —  Fast preview/print using the Word RSL template.

Same pattern as print_engine.py (Excel): keeps one Word instance open in the
background so the first preview takes a few seconds (starting Word) and every
one after that is near-instant. Runs on a dedicated thread — the safe way to
reuse a COM object across web requests — and recovers automatically if you
close Word.

SPEED-UP (standby doc): the slow part of every print used to be the
Documents.Open() call needed to get a fresh, never-touched copy of the
template (correctness reason: reusing one live document let old field text
bleed into new ones — see _ensure below). Now, right after finishing a job
and while the thread is idle waiting for the next one, we quietly open the
NEXT fresh copy in the background (minimized, out of the way) and hold onto
it. When the next print request comes in, we swap that pre-opened copy in
instantly instead of paying the Open() cost on the critical path. Nothing
about the actual correctness guarantee changes — every document handed to a
job is still opened fresh and never reused; we've just moved *when* the
opening happens from "during the request" to "during idle time before it."
"""

import os
import threading
import queue
from app.legacy import print_stage_word

TEMPLATE_FILE = "RSL_Format_2025_mapped.docx"
WD_FIELD_MERGEFIELD = 59
WD_PRINT_PREVIEW = 4
WD_NORMAL_VIEW = 1
WD_WINDOW_STATE_NORMAL = 0
WD_WINDOW_STATE_MINIMIZE = 2


def _update_field_collection(fields, values):
    n = 0
    for field in fields:
        try:
            if field.Type != WD_FIELD_MERGEFIELD:
                continue
            code = field.Code.Text
            name = code.replace("MERGEFIELD", "").replace('"', "").replace('“', "").replace('”', "").strip()
            if name in values:
                field.Result.Text = values[name]
                n += 1
        except Exception:
            continue   # never let one broken field stop the rest of the line
    return n


MSO_GROUP = 6   # MsoShapeType.msoGroup

def _update_all_fields(doc, values):
    """
    Update every MERGEFIELD in the document — both in the main body (doc.Fields)
    and inside floating text boxes, which Word keeps in a SEPARATE collection
    (doc.Fields does NOT reach inside text boxes; each shape's own TextFrame
    has to be visited individually). Also recurses into grouped shapes, since
    a shape that's part of a Group isn't reachable directly — only its
    top-level Group container shows up in doc.Shapes.
    """
    total = _update_field_collection(doc.Fields, values)
    total += _update_shapes_recursive(doc.Shapes, values)
    return total


def _update_shapes_recursive(shapes, values):
    total = 0
    for shape in shapes:
        try:
            if shape.Type == MSO_GROUP:
                total += _update_shapes_recursive(shape.GroupItems, values)
                continue
        except Exception:
            pass
        try:
            if shape.TextFrame.HasText:
                total += _update_field_collection(shape.TextFrame.TextRange.Fields, values)
        except Exception:
            continue  # shapes with no text frame (e.g. the OR stamp picture) raise here
    return total


class _Job:
    def __init__(self, lic_id, mode):
        self.lic_id = lic_id
        self.mode = mode
        self.done = threading.Event()
        self.ok = False
        self.error = None


def _get_pid_from_hwnd(hwnd):
    """Turn a window handle into the process ID that owns it — lets us
    target exactly the Word instance this code started, nothing else."""
    try:
        import win32process
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return pid
    except Exception:
        return None


def _bring_to_front(hwnd):
    """
    Force a window to the foreground and un-minimize it if needed.

    Word's own COM .Activate() call routinely gets silently ignored by
    Windows here, because the caller is a background Python thread, not
    something the user just clicked -- Windows treats that as
    focus-stealing and blocks it by design, which is why the print/preview
    window kept collapsing to the taskbar instead of actually appearing.

    Workaround: temporarily "borrow" the currently-focused window's input
    state (AttachThreadInput) so SetForegroundWindow is allowed to
    succeed for our window too. This is the standard Win32 idiom for this
    exact problem -- not 100% guaranteed by Windows in every situation,
    but far more reliable than relying on .Activate() alone. Implemented
    via ctypes directly against user32.dll rather than pywin32's
    win32process/win32gui wrappers, since AttachThreadInput's exact home
    module varies across pywin32 versions.
    """
    if not hwnd:
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        SW_RESTORE = 9

        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)

        fg_hwnd = user32.GetForegroundWindow()
        target_pid = ctypes.c_ulong(0)
        target_tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(target_pid))
        fg_tid = 0
        if fg_hwnd:
            fg_pid = ctypes.c_ulong(0)
            fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, ctypes.byref(fg_pid))

        attached = False
        if fg_tid and fg_tid != target_tid:
            attached = bool(user32.AttachThreadInput(fg_tid, target_tid, True))

        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(fg_tid, target_tid, False)
    except Exception:
        pass


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
    Last-resort safety net: if the specific Word process we started is
    STILL running a few seconds after we asked it to quit nicely, force it
    closed. Only ever targets that exact process ID — never a blanket
    'close all Word' — so it can't touch a Word window you opened yourself
    for something unrelated.
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


class _WordPrinterService(threading.Thread):
    """Owns one Word instance on its own thread and processes print jobs."""
    def __init__(self, db_path, here):
        super().__init__(daemon=True)
        self.db_path = db_path
        self.here = here
        self.q = queue.Queue()
        self.word = None
        self.doc = None
        self.standby_doc = None   # a fresh, never-touched copy opened ahead
                                   # of time during idle periods — see module
                                   # docstring
        self.word_pid = None   # the exact process this service started — used
                                # as a last-resort safety net on shutdown

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
                # Idle time before the next request arrives — a good moment
                # to quietly pre-open tomorrow's (or the next click's) fresh
                # template copy so it's ready to swap in instantly.
                try:
                    self._replenish_standby(win32)
                except Exception:
                    pass
        finally:
            try:
                if self.word is not None:
                    # suppress any "Save changes?" prompt — without this, Word
                    # can hang waiting for an answer nobody's there to give,
                    # leaving WINWORD.EXE running as an orphaned process even
                    # after the app has closed
                    self.word.DisplayAlerts = False
                    try:
                        self.word.ActiveDocument.Saved = True
                    except Exception:
                        pass
                    # close EVERY open document, not just the one we were
                    # tracking (this also catches the standby copy) — during
                    # Multi-Edit Mode several fill jobs run back-to-back, and
                    # we want to be certain none are left in a "modified"
                    # state that could block Quit()
                    try:
                        for d in list(self.word.Documents):
                            try:
                                d.Saved = True
                                d.Close(SaveChanges=False)
                            except Exception:
                                pass
                    except Exception:
                        pass
                    self.word.Quit(SaveChanges=False)
            except Exception:
                pass
            pythoncom.CoUninitialize()

    def _open_fresh_doc(self, win32, minimize=False):
        """Start Word if needed, then open one brand-new, untouched copy of
        the template. This is the (relatively slow) operation we now try to
        run ahead of time instead of during a live request."""
        template_path = os.path.join(self.here, TEMPLATE_FILE)
        try:
            os.remove(template_path + ":Zone.Identifier")   # unblock if downloaded
        except OSError:
            pass

        if self.word is None or not self._word_alive():
            self.word = win32.Dispatch("Word.Application")
            self.word.Visible = True
            self.word_pid = _get_pid_from_hwnd(self.word.Hwnd)
            # Word can accept COM calls a moment before it has actually finished
            # starting up — driving it immediately on a cold start is what
            # caused the first Open/Preview to show an unfilled template.
            # A short pause here lets Word settle before we touch it.
            import time
            time.sleep(1.2)

        doc = self.word.Documents.Open(template_path, ReadOnly=False)
        if minimize:
            # keep the pre-opened standby copy out of the way so it doesn't
            # steal focus from whatever the person is currently looking at
            try:
                doc.ActiveWindow.WindowState = WD_WINDOW_STATE_MINIMIZE
            except Exception:
                pass
        return doc

    def _ensure(self, win32):
        """
        Return a fresh, untouched document ready for field-filling. Reusing
        one open document across many prints let old field text bleed into
        new ones after repeated edits (Word's field boundaries can drift
        after several programmatic changes) — so instead we keep the Word
        *application* open for speed, but the *document* is always a fresh
        copy, which is the reliable way to guarantee no leftover data.

        Fast path: if a standby copy was already pre-opened during idle
        time, swap it in immediately — no Documents.Open on this request.
        Fallback: on a cold start (no standby ready yet), open one now,
        exactly as before.
        """
        old_doc = self.doc

        if self.standby_doc is not None:
            self.doc = self.standby_doc
            self.standby_doc = None
            try:
                self.doc.ActiveWindow.WindowState = WD_WINDOW_STATE_NORMAL
                self.doc.Activate()
            except Exception:
                pass
        else:
            self.doc = self._open_fresh_doc(win32)

        if old_doc is not None:
            try:
                old_doc.Close(SaveChanges=False)
            except Exception:
                pass

        return self.doc

    def _replenish_standby(self, win32):
        """Called between jobs, on this same dedicated thread, while it has
        nothing else to do — opens the next fresh template copy now so a
        later print request can skip Documents.Open entirely."""
        if self.standby_doc is not None or self.word is None:
            return
        if not self._word_alive():
            return
        try:
            self.standby_doc = self._open_fresh_doc(win32, minimize=True)
            if self.doc is not None:
                self.doc.Activate()   # restore focus to whatever's on screen
        except Exception:
            self.standby_doc = None

    def _word_alive(self):
        try:
            _ = self.word.Visible
            return True
        except Exception:
            return False

    def _process(self, job, win32):
        rec = print_stage_word.fetch_record(self.db_path, job.lic_id)
        if not rec:
            job.ok = False
            job.done.set()
            return
        doc = self._ensure(win32)
        values = print_stage_word.word_field_values(rec)

        updated = _update_all_fields(doc, values)
        if updated == 0:
            # Word likely wasn't fully ready yet (cold start) — the fill silently
            # did nothing. Give it a moment and try once more before giving up.
            import time
            time.sleep(0.8)
            updated = _update_all_fields(doc, values)

        # Release the web request now — the data is in place.
        job.ok = True
        job.done.set()

        if job.mode == "fill":
            # quiet background sync (e.g. clicking through pinned map stations) —
            # update the fields only, never bring Word forward or change its view
            return

        try:
            self.word.Visible = True
            self.word.Activate()
            _bring_to_front(self.word.Hwnd)
        except Exception:
            pass

        _force_redraw(self.word, doc)

        if job.mode == "open":
            pass          # just show the filled-in document — no print/preview
        elif job.mode == "preview":
            self.word.ActiveWindow.View.Type = WD_PRINT_PREVIEW
        else:
            doc.PrintOut()


def _force_redraw(word, doc):
    """
    Word sometimes updates a field's stored result (what we just did) without
    visually repainting shapes/text boxes on screen — so Print Preview can
    show stale content even though the data changed correctly underneath.
    Toggling field-code display forces Word to fully redraw every field.
    """
    try:
        win = word.ActiveWindow
        win.View.ShowFieldCodes = True
        win.View.ShowFieldCodes = False
    except Exception:
        pass
    try:
        doc.Repaginate()
    except Exception:
        pass
    try:
        word.ScreenRefresh()
    except Exception:
        pass


_service = None
_lock = threading.Lock()


def _get_service(db_path):
    global _service
    with _lock:
        if _service is None or not _service.is_alive():
            here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root (was: this script's own folder) -- these files moved into app/legacy/ during the FastAPI restructuring, but the template/output files (PRINT_ready.xlsx, RSL_Format_2025_mapped.docx, telco.db, etc.) still live in the project root next to start.bat, not next to this .py file
            db_full = db_path if os.path.isabs(db_path) else os.path.join(here, db_path)
            _service = _WordPrinterService(db_full, here)
            _service.start()
    return _service


def print_one(lic_id, db_path, mode="preview"):
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root (was: this script's own folder) -- these files moved into app/legacy/ during the FastAPI restructuring, but the template/output files (PRINT_ready.xlsx, RSL_Format_2025_mapped.docx, telco.db, etc.) still live in the project root next to start.bat, not next to this .py file
    if not os.path.exists(os.path.join(here, TEMPLATE_FILE)):
        raise FileNotFoundError(f"{TEMPLATE_FILE} not found in {here}")
    try:
        import win32com.client  # noqa
    except ImportError:
        raise RuntimeError("pywin32 not installed. Run: pip install pywin32")
    return _get_service(db_path).submit(lic_id, mode)


def shutdown():
    """Close the background Word when the app stops."""
    global _service
    pid = _service.word_pid if _service is not None else None
    if _service is not None and _service.is_alive():
        _service.stop()
        _service.join(timeout=10)
    _service = None
    # graceful shutdown had 10 seconds to close things down properly above —
    # if Word is somehow still running after that, this is the hard fallback,
    # targeting only that exact process
    force_close_if_stuck(pid, wait_seconds=1)
