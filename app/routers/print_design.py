"""app/routers/print_design.py — the built-in Live Preview / PDF export
feature (see app/legacy/print_builtin.py for the "why"). Separate from
app/routers/print.py, which still runs the original Excel/Word print flow
unchanged -- this is purely additive.
"""
import io
import re
import zipfile

from fastapi import APIRouter, HTTPException, Body, Request, Response

from app.core import require_permission
from app.legacy import print_builtin

router = APIRouter(tags=["print-design"])


@router.get("/api/print-template")
def get_print_template(request: Request):
    require_permission(request, "can_print")
    return print_builtin.load_template()


@router.get("/api/print-template/default")
def get_default_print_template(request: Request):
    """The untouched factory layout -- 'Reset to Default' in Design mode."""
    require_permission(request, "can_print")
    return print_builtin.load_default_template()


@router.put("/api/print-template")
def update_print_template(data: dict = Body(...), request: Request = None):
    """Saves the certificate layout (box positions/sizes/font sizes) from
    Live Preview's Design mode. Whole-template replace, same as every other
    settings-style save in this app -- the frontend always sends the full
    current template back, never a partial patch."""
    require_permission(request, "can_print")
    if "boxes" not in data:
        raise HTTPException(400, "Template must include a 'boxes' list")
    print_builtin.save_template(data)
    return {"ok": True}


@router.post("/api/print-template/set-default")
def set_default_print_template(request: Request):
    """'Set as My Default' -- makes the CURRENT saved layout what 'Reset to
    Default' recalls, instead of the original factory layout."""
    require_permission(request, "can_print")
    print_builtin.save_as_default(print_builtin.load_template())
    return {"ok": True}


@router.get("/api/print-template/history")
def list_print_template_history(request: Request):
    """Named/versioned layout saves -- newest last. Data itself isn't
    included here (list view only) to keep this light; fetch a specific
    entry's data via GET .../history/{id}."""
    require_permission(request, "can_print")
    entries = print_builtin.load_history()
    return {"history": [{"id": e["id"], "name": e["name"], "saved_at": e["saved_at"]} for e in entries]}


@router.post("/api/print-template/history")
def save_print_template_history(data: dict = Body(...), request: Request = None):
    """Saves the CURRENT in-browser layout (sent by the frontend, same as
    PUT /api/print-template) as a new named history entry -- doesn't touch
    the live template, just adds a recall point."""
    require_permission(request, "can_print")
    name = (data.get("name") or "").strip()
    tpl = data.get("template")
    if not tpl or "boxes" not in tpl:
        raise HTTPException(400, "Missing template data to save")
    entry = print_builtin.add_history_entry(name, tpl)
    return {"ok": True, "id": entry["id"], "name": entry["name"], "saved_at": entry["saved_at"]}


@router.get("/api/print-template/history/{entry_id}")
def get_print_template_history_entry(entry_id: int, request: Request):
    require_permission(request, "can_print")
    entry = print_builtin.get_history_entry(entry_id)
    if not entry:
        raise HTTPException(404, "That saved layout no longer exists")
    return entry["data"]


@router.post("/api/print-template/history/{entry_id}/restore")
def restore_print_template_history_entry(entry_id: int, request: Request):
    """Loads a saved layout back as the LIVE template -- same effect as
    pasting it in and clicking Save Layout."""
    require_permission(request, "can_print")
    entry = print_builtin.get_history_entry(entry_id)
    if not entry:
        raise HTTPException(404, "That saved layout no longer exists")
    print_builtin.save_template(entry["data"])
    return {"ok": True}


@router.delete("/api/print-template/history/{entry_id}")
def delete_print_template_history_entry(entry_id: int, request: Request):
    require_permission(request, "can_print")
    if not print_builtin.delete_history_entry(entry_id):
        raise HTTPException(404, "That saved layout no longer exists")
    return {"ok": True}


@router.get("/api/print-data/{lic_id}")
def get_print_data(lic_id: int, request: Request):
    """Every field on this record, formatted the same way the PDF export
    formats them (dates as 'August 14, 2025', etc.) -- Live Preview drops
    these straight into the template's boxes."""
    require_permission(request, "can_print")
    record = print_builtin.fetch_record(lic_id)
    if not record:
        raise HTTPException(404, f"Record {lic_id} not found")
    return {"ok": True, "fields": print_builtin.formatted_fields(record)}


@router.get("/api/print-pdf/{lic_id}")
def get_print_pdf(lic_id: int, request: Request):
    require_permission(request, "can_print")
    try:
        pdf_bytes = print_builtin.build_pdf(lic_id)
    except Exception as e:
        raise HTTPException(500, f"Could not generate the PDF: {e}")
    if pdf_bytes is None:
        raise HTTPException(404, f"Record {lic_id} not found")
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="License_{lic_id}.pdf"'},
    )


@router.get("/api/print-pdf-batch")
def get_print_pdf_batch(ids: str, request: Request):
    """Mass Print for Batch Review -- one PDF per selected record, all
    packaged into a single ZIP so the user gets one download instead of
    triggering N separate browser downloads."""
    require_permission(request, "can_print")
    id_list = []
    for piece in ids.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            id_list.append(int(piece))
        except ValueError:
            continue
    if not id_list:
        raise HTTPException(400, "No record ids given")

    zip_buf = io.BytesIO()
    used_names = set()
    added = 0
    total = len(id_list)
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, lic_id in enumerate(id_list, start=1):
            try:
                pdf_bytes = print_builtin.build_pdf(lic_id, batch_index=i, batch_total=total)
            except Exception:
                continue
            if pdf_bytes is None:
                continue
            record = print_builtin.fetch_record(lic_id)
            license_no = (record or {}).get("license_no") or f"License_{lic_id}"
            safe_name = re.sub(r'[\\/:*?"<>|]', "_", str(license_no)).strip() or f"License_{lic_id}"
            name = f"{safe_name}.pdf"
            n = 2
            while name in used_names:
                name = f"{safe_name}_{n}.pdf"
                n += 1
            used_names.add(name)
            zf.writestr(name, pdf_bytes)
            added += 1

    if added == 0:
        raise HTTPException(404, "None of the given records could be found")

    return Response(
        content=zip_buf.getvalue(), media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="Batch_Print.zip"'},
    )
