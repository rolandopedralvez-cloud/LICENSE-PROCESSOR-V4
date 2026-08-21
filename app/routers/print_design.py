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
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for lic_id in id_list:
            try:
                pdf_bytes = print_builtin.build_pdf(lic_id)
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
