"""app/routers/print.py — /api/print/{id}, /api/print-word/{id}. Thin
wrappers calling app.legacy.print_engine* unchanged (Windows/COM only)."""
from fastapi import APIRouter, HTTPException, Request

from app.config import DB
from app.core import get_conn, role_for, require_permission, log_activity

router = APIRouter(tags=["print"])

@router.post("/api/print/{lic_id}")
def print_record(lic_id: int, mode: str = "preview", request: Request = None):
    """
    Preview, print, or open one record's RSL (FRONT page) via Excel.
    mode = 'preview' opens Excel's Print Preview; 'print' sends to the printer;
    'open' just shows the filled-in workbook for viewing/editing.
    Runs only on the PC where the backend runs (needs Excel + pywin32).
    """
    require_permission(request, "can_print")
    if mode not in ("preview", "print", "open"):
        raise HTTPException(400, "mode must be 'preview', 'print', or 'open'")
    try:
        from app.legacy import print_engine
    except ImportError:
        raise HTTPException(500, "app/legacy/print_engine.py not found")
    try:
        ok = print_engine.print_one(lic_id, DB, mode)
    except FileNotFoundError as e:
        raise HTTPException(500, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    if not ok:
        raise HTTPException(404, f"Record {lic_id} not found")
    return {"ok": True, "id": lic_id, "mode": mode}


@router.post("/api/print-word/{lic_id}")
def print_record_word(lic_id: int, mode: str = "preview", request: Request = None):
    """
    Preview, print, open, or quietly fill one record's RSL using the Word template.
    mode = 'preview' opens Word's Print Preview; 'print' sends to the printer;
    'open' just shows the filled-in document for viewing/editing; 'fill' quietly
    updates the document's fields with no visible window change — used to keep
    Word in sync while clicking through pinned stations on the map, without
    popping anything open each time.
    Runs only on the PC where the backend runs (needs Word + pywin32).
    """
    require_permission(request, "can_print")
    if mode not in ("preview", "print", "fill", "open"):
        raise HTTPException(400, "mode must be 'preview', 'print', 'open', or 'fill'")
    try:
        from app.legacy import print_engine_word
    except ImportError:
        raise HTTPException(500, "app/legacy/print_engine_word.py not found")
    try:
        ok = print_engine_word.print_one(lic_id, DB, mode)
    except FileNotFoundError as e:
        raise HTTPException(500, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    if not ok:
        raise HTTPException(404, f"Record {lic_id} not found")
    return {"ok": True, "id": lic_id, "mode": mode}
# (IMPORT_CACHE used to be defined here — moved to app/core.py, see
# app/routers/import_.py for its user)
