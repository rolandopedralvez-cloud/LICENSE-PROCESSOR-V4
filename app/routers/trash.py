"""app/routers/trash.py — /api/trash, /restore, /purge, /trash/empty,
/api/wipe-all. Moved verbatim from main.py."""
import os
from fastapi import APIRouter, HTTPException, Body, Request

from app.config import DB
from app.core import get_conn, role_for, require_permission, log_activity, require_super_admin

router = APIRouter(tags=["trash"])

@router.get("/api/trash")
def list_trash():
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, license_no, licensee, site_name, brgy, town, province, "
        "class_of_station, tech, license_status, or_no, deleted_at "
        "FROM licenses WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC").fetchall()
    conn.close()
    return {"count": len(rows), "results": [dict(r) for r in rows]}


@router.post("/api/licenses/{lic_id}/restore")
def restore_license(lic_id: int, request: Request):
    require_permission(request, "can_delete")
    conn = get_conn()
    row = conn.execute("SELECT license_no FROM licenses WHERE id = ?", (lic_id,)).fetchone()
    cur = conn.execute(
        "UPDATE licenses SET deleted_at = NULL WHERE id = ? AND deleted_at IS NOT NULL",
        (lic_id,))
    conn.commit(); conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "Record not in trash")
    log_activity(request, "restore", license_id=lic_id, license_no=row["license_no"] if row else None,
                 detail="Restored from Trash")
    return {"ok": True, "restored": lic_id}


@router.delete("/api/licenses/{lic_id}/purge")
def purge_license(lic_id: int, request: Request):
    """Permanently delete one trashed record (cannot be undone)."""
    require_permission(request, "can_purge")
    conn = get_conn()
    row = conn.execute("SELECT license_no FROM licenses WHERE id = ?", (lic_id,)).fetchone()
    cur = conn.execute(
        "DELETE FROM licenses WHERE id = ? AND deleted_at IS NOT NULL", (lic_id,))
    conn.commit(); conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "Record not in trash")
    log_activity(request, "purge", license_id=lic_id, license_no=row["license_no"] if row else None,
                 detail="Permanently deleted")
    return {"ok": True, "purged": lic_id}


@router.post("/api/trash/empty")
def empty_trash(request: Request):
    """Permanently delete everything in the Trash (cannot be undone)."""
    require_permission(request, "can_purge")
    conn = get_conn()
    cur = conn.execute("DELETE FROM licenses WHERE deleted_at IS NOT NULL")
    conn.commit(); n = cur.rowcount; conn.close()
    log_activity(request, "purge", detail=f"Trash emptied — {n} record(s) permanently deleted")
    return {"ok": True, "purged": n}


@router.post("/api/wipe-all")
def wipe_all(data: dict = Body(...), request: Request = None):
    """
    Delete EVERY record (licenses + payments). Super Admin only.
    Requires the exact confirmation phrase "DELETE ALL" to proceed.
    Always backs up telco.db first — this cannot be undone otherwise.
    """
    require_super_admin(request)
    import shutil, os, datetime
    if (data.get("confirm") or "").strip() != "DELETE ALL":
        raise HTTPException(400, 'Type "DELETE ALL" exactly to confirm.')

    backup = None
    try:
        if os.path.exists(DB):
            backup = f"telco_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
            shutil.copy(DB, backup)
    except Exception as e:
        raise HTTPException(500, f"Could not create backup, aborted for safety: {e}")

    conn = get_conn()
    n_lic = conn.execute("SELECT COUNT(*) FROM licenses").fetchone()[0]
    conn.execute("DELETE FROM payments")
    conn.execute("DELETE FROM licenses")
    try:
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('licenses','payments')")
    except Exception:
        pass
    conn.commit(); conn.close()
    return {"ok": True, "deleted": n_lic, "backup": backup}

# ---------------------------------------------------------------- payments
# ---------------------------------------------------------------- BATCH RENEW
