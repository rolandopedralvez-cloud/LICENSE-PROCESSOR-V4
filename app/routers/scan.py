"""app/routers/scan.py — /api/scan*. Moved verbatim from main.py."""
import os
import json
import base64
import datetime
from fastapi import APIRouter, HTTPException, Body, Query, Request
from fastapi.responses import FileResponse

from app.config import DB
from app.core import (
    get_conn, cols, clean_payload, role_for, require_permission, log_activity,
    _current_user_info, PROTECTED, SCAN_DIR, SCAN_MODEL,
)

router = APIRouter(tags=["scan"])

def _scan_field_labels():
    from app.legacy import print_stage
    return {f: h for h, f in zip(print_stage.STAGING_HEADERS, print_stage.STAGING_FIELDS) if f}

def _extract_scan_fields(file_bytes, mime_type, filename):
    """Send one scanned RSL image/PDF to Claude's vision API and ask it to
    read off the known form fields as JSON. Returns (fields_dict,
    low_confidence_list, error_string_or_None). Never raises — a failed
    read still creates a quarantine entry (with all fields blank) so the
    upload isn't lost; the person can fill it in by hand instead."""
    import base64, json as _json, os as _os, re as _re

    api_key = _os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {}, [], ("ANTHROPIC_API_KEY is not set on this PC — the scan was saved but "
                         "couldn't be read automatically. Fill in the fields by hand below, "
                         "or ask your administrator to set the API key and re-upload.")
    try:
        import anthropic
    except ImportError:
        return {}, [], "The 'anthropic' package isn't installed (pip install anthropic). Scan saved but not read."

    labels = _scan_field_labels()
    field_list = "\n".join(f"- {k}: {v}" for k, v in labels.items())
    prompt = (
        "This is a scanned National Telecommunications Commission (NTC) Radio Station "
        "License (RSL) form. Read every field you can find on it and return ONLY a JSON "
        "object (no markdown fences, no commentary) with this exact shape:\n"
        '{"fields": {"<field_key>": "<value or null>", ...}, '
        '"low_confidence_fields": ["<field_key>", ...]}\n\n'
        "Use exactly these field keys (left = key to use, right = what it means on the form):\n"
        f"{field_list}\n\n"
        "Rules: only fill a field if it's actually visible on the form — use null for "
        "anything blank, illegible, or not present, don't guess. Dates must be "
        "'YYYY-MM-DD'. If a field is legible but you're not fully certain (unclear "
        "handwriting, smudged, partly cut off), still give your best reading AND add its "
        "key to low_confidence_fields so a person double-checks it. Return valid JSON only."
    )

    b64 = base64.b64encode(file_bytes).decode("ascii")
    if mime_type == "application/pdf":
        content_block = {"type": "document", "source": {"type": "base64", "media_type": mime_type, "data": b64}}
    else:
        content_block = {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": b64}}

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=SCAN_MODEL, max_tokens=2000,
            messages=[{"role": "user", "content": [content_block, {"type": "text", "text": prompt}]}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        text = _re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=_re.M).strip()
        parsed = _json.loads(text)
        fields = parsed.get("fields") or {}
        low_conf = parsed.get("low_confidence_fields") or []
        # keep only real STAGING fields, ignore anything the model invented
        fields = {k: v for k, v in fields.items() if k in labels and v not in (None, "", "null")}
        low_conf = [k for k in low_conf if k in labels]
        return fields, low_conf, None
    except Exception as e:
        return {}, [], f"Could not read this scan automatically ({e}). Fill in the fields by hand below."

@router.get("/api/scan/field-catalog")
def scan_field_catalog(request: Request = None):
    """Field keys + labels for building the quarantine review/edit form on
    the frontend, in the same order as the rest of the app's Export/Import
    layout."""
    require_permission(request, "can_import")
    labels = _scan_field_labels()
    return {"fields": [{"key": k, "label": v} for k, v in labels.items()]}


@router.post("/api/scan/upload")
def upload_scan(data: dict = Body(...), request: Request = None):
    require_permission(request, "can_import")
    """Save an uploaded scan and quarantine it with an automatic first-draft
    reading. Nothing is added to the real database here."""
    import base64, datetime as _dt, os as _os, re as _re, secrets as _secrets, json as _json

    b64 = data.get("b64", "")
    filename = (data.get("filename") or "scan").strip()
    if not b64:
        raise HTTPException(400, "No file received")
    header, _, payload = b64.partition(",")
    mime_type = "image/jpeg"
    m = _re.match(r"data:([\w/\-.+]+);base64", header)
    if m:
        mime_type = m.group(1)
    elif not payload:
        payload = b64  # no data: prefix was sent, whole string is the b64 payload

    try:
        file_bytes = base64.b64decode(payload or b64)
    except Exception:
        raise HTTPException(400, "Could not read that file")

    if mime_type not in ("image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"):
        raise HTTPException(400, "Please upload a JPG, PNG, WEBP, GIF, or PDF scan")

    _os.makedirs(SCAN_DIR, exist_ok=True)
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
           "image/gif": ".gif", "application/pdf": ".pdf"}[mime_type]
    safe_name = _re.sub(r"[^\w.\-]", "_", filename)[:80]
    stored_name = f"{_dt.datetime.now().strftime('%Y%m%d%H%M%S')}_{_secrets.token_hex(4)}_{safe_name}{ext if not safe_name.lower().endswith(ext) else ''}"
    stored_path = _os.path.join(SCAN_DIR, stored_name)
    with open(stored_path, "wb") as f:
        f.write(file_bytes)

    fields, low_conf, err = _extract_scan_fields(file_bytes, mime_type, filename)

    info = _current_user_info(request)
    username = info["username"] if info else None
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO quarantine_scans (ts, uploaded_by, filename, stored_path, status, "
        "extracted_json, corrected_json, low_confidence, extract_error) VALUES (?,?,?,?,?,?,?,?,?)",
        (now, username, filename, stored_path, "pending",
         _json.dumps(fields), _json.dumps(fields), _json.dumps(low_conf), err))
    scan_id = cur.lastrowid
    conn.commit(); conn.close()
    log_activity(request, "scan_upload", detail=f"Uploaded scan '{filename}' for quarantine review" + (f" — {err}" if err else ""))
    return {"ok": True, "id": scan_id, "fields": fields, "low_confidence_fields": low_conf, "error": err}


@router.get("/api/scan/quarantine")
def list_quarantine_scans(status: str = "", q: str = "", limit: int = 200, request: Request = None):
    require_permission(request, "can_import")
    import json as _json
    conn = get_conn()
    clauses, params = [], []
    if status:
        clauses.append("status = ?"); params.append(status)
    if q:
        clauses.append("(filename LIKE ? OR extracted_json LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    clause = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM quarantine_scans {clause} ORDER BY id DESC LIMIT ?", params + [limit]).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        for key in ("extracted_json", "corrected_json"):
            try: d[key.replace("_json", "")] = _json.loads(d.pop(key) or "{}")
            except Exception: d[key.replace("_json", "")] = {}
        try: d["low_confidence"] = _json.loads(d["low_confidence"] or "[]")
        except Exception: d["low_confidence"] = []
        out.append(d)
    return {"count": len(out), "results": out}


@router.get("/api/scan/{scan_id}/file")
def get_scan_file(scan_id: int, request: Request = None):
    require_permission(request, "can_import")
    conn = get_conn()
    row = conn.execute("SELECT stored_path, filename FROM quarantine_scans WHERE id = ?", (scan_id,)).fetchone()
    conn.close()
    if not row or not row["stored_path"] or not os.path.exists(row["stored_path"]):
        raise HTTPException(404, "Scan file not found")
    return FileResponse(row["stored_path"], filename=row["filename"] or "scan")


@router.put("/api/scan/{scan_id}")
def update_quarantine_scan(scan_id: int, data: dict = Body(...), request: Request = None):
    require_permission(request, "can_import")
    """Save the person's corrections to the extracted draft. Doesn't touch
    the real database — still just editing the quarantined copy."""
    import json as _json
    fields = data.get("fields")
    if not isinstance(fields, dict):
        raise HTTPException(400, "fields must be an object")
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM quarantine_scans WHERE id = ?", (scan_id,)).fetchone():
        conn.close(); raise HTTPException(404, "Scan not found")
    conn.execute("UPDATE quarantine_scans SET corrected_json = ?, status = CASE WHEN status = 'pending' THEN 'corrected' ELSE status END WHERE id = ?",
                 (_json.dumps(fields), scan_id))
    conn.commit(); conn.close()
    return {"ok": True, "id": scan_id}


@router.post("/api/scan/{scan_id}/approve")
def approve_quarantine_scan(scan_id: int, request: Request = None):
    require_permission(request, "can_import")
    """Push a corrected quarantine draft into the real database — but only
    if its license number doesn't already exist. If it does, this refuses
    and hands back the existing record so nothing gets silently duplicated
    or clobbered; the reviewer edits the existing record directly instead."""
    import json as _json, datetime as _dt
    conn = get_conn()
    row = conn.execute("SELECT * FROM quarantine_scans WHERE id = ?", (scan_id,)).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "Scan not found")
    if row["status"] == "approved":
        conn.close(); raise HTTPException(400, "This scan was already approved")
    try:
        fields = _json.loads(row["corrected_json"] or row["extracted_json"] or "{}")
    except Exception:
        fields = {}
    lic_no = str(fields.get("license_no") or "").strip()
    if not lic_no:
        conn.close(); raise HTTPException(400, "License No. is required before this can be approved")

    existing = conn.execute("SELECT * FROM licenses WHERE TRIM(license_no) = TRIM(?) ORDER BY id DESC LIMIT 1", (lic_no,)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(409, f"License {lic_no} already exists in the database (record #{existing['id']}). "
                                  f"Edit that record directly instead of approving this scan as a new one.")

    writable = set(cols(conn, "licenses")) - PROTECTED
    payload = {k: v for k, v in fields.items() if k in writable and v not in (None, "")}
    if not payload:
        conn.close(); raise HTTPException(400, "No usable fields to save")
    field_names = list(payload.keys())
    sql = f"INSERT INTO licenses ({','.join(field_names)}) VALUES ({','.join('?'*len(field_names))})"
    cur = conn.execute(sql, [payload[f] for f in field_names])
    new_id = cur.lastrowid

    info = _current_user_info(request)
    username = info["username"] if info else None
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("UPDATE quarantine_scans SET status = 'approved', license_id = ?, reviewed_by = ?, reviewed_ts = ? WHERE id = ?",
                 (new_id, username, now, scan_id))
    conn.commit(); conn.close()
    log_activity(request, "create", license_id=new_id, license_no=lic_no,
                 detail=f"Added from scanned upload '{row['filename']}' (quarantine #{scan_id})")
    return {"ok": True, "license_id": new_id}


@router.post("/api/scan/{scan_id}/reject")
def reject_quarantine_scan(scan_id: int, data: dict = Body(default={}), request: Request = None):
    require_permission(request, "can_import")
    import datetime as _dt
    reason = (data.get("reason") or "").strip()
    info = _current_user_info(request)
    username = info["username"] if info else None
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    row = conn.execute("SELECT filename FROM quarantine_scans WHERE id = ?", (scan_id,)).fetchone()
    if not row:
        conn.close(); raise HTTPException(404, "Scan not found")
    conn.execute("UPDATE quarantine_scans SET status = 'rejected', reviewed_by = ?, reviewed_ts = ? WHERE id = ?",
                 (username, now, scan_id))
    conn.commit(); conn.close()
    log_activity(request, "scan_reject", detail=f"Rejected scanned upload '{row['filename']}' (quarantine #{scan_id})" + (f" — {reason}" if reason else ""))
    return {"ok": True, "id": scan_id}
