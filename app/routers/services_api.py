"""app/routers/services_api.py — API for the "Other Services" feature (see
app/legacy/services_builtin.py for the full "why"). Entirely separate from
every Telco RSL route -- reuses can_create/can_edit/can_delete/can_print/
can_export the same way the Telco RSL side does, no new permission types
to explain to users.
"""
import io
import re
import zipfile

from fastapi import APIRouter, HTTPException, Body, Request, Response

from app.core import require_permission, require_super_admin, _current_user_info
from app.legacy import services_builtin as sb

router = APIRouter(tags=["services"])


def _requester(request):
    info = _current_user_info(request)
    return (info["username"], info["role"]) if info else (None, None)


def _svc_or_403(service_id, request):
    """Fetches the service, 404s if it doesn't exist, and 403s if this
    service has been restricted to specific users (see 'Restrict Access'
    on the Other Services list) and this user isn't one of them."""
    svc = sb.get_service(service_id)
    if not svc:
        raise HTTPException(404, "Service not found")
    username, role = _requester(request)
    if not sb.user_can_access_service(svc, username, role):
        raise HTTPException(403, "You don't have access to this service.")
    return svc


# ---------------------------------------------------------------- categories
@router.get("/api/service-types")
def api_list_types(request: Request):
    require_permission(request, "can_create")
    return {"types": sb.list_types()}


@router.post("/api/service-types")
def api_add_type(data: dict = Body(...), request: Request = None):
    require_permission(request, "can_create")
    try:
        return sb.add_type(data.get("name"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/api/service-natures")
def api_list_natures(request: Request):
    require_permission(request, "can_create")
    return {"natures": sb.list_natures()}


@router.post("/api/service-natures")
def api_add_nature(data: dict = Body(...), request: Request = None):
    require_permission(request, "can_create")
    try:
        return sb.add_nature(data.get("name"))
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------- services
@router.get("/api/services")
def api_list_services(request: Request):
    require_permission(request, "can_create")
    username, role = _requester(request)
    return {"services": sb.list_services(username=username, role=role)}


@router.post("/api/services")
def api_create_service(data: dict = Body(...), request: Request = None):
    require_permission(request, "can_create")
    try:
        return sb.create_service(data.get("name"), data.get("type_id"), data.get("nature_id"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/api/services/{service_id}")
def api_get_service(service_id: int, request: Request):
    require_permission(request, "can_create")
    svc = _svc_or_403(service_id, request)
    return svc


@router.put("/api/services/{service_id}")
def api_update_service(service_id: int, data: dict = Body(...), request: Request = None):
    require_permission(request, "can_edit")
    _svc_or_403(service_id, request)
    svc = sb.update_service_meta(service_id, data.get("name"), data.get("type_id"),
                                  data.get("nature_id"), data.get("archived"),
                                  data.get("board_field"), data.get("expiry_field"))
    if not svc:
        raise HTTPException(404, "Service not found")
    return svc


@router.put("/api/services/{service_id}/restricted-users")
def api_save_restricted_users(service_id: int, data: dict = Body(...), request: Request = None):
    """Who can see/use this service -- empty list means everyone (the
    default). Super-admin only, same as every other Manage Users action."""
    require_super_admin(request)
    if not sb.get_service(service_id):
        raise HTTPException(404, "Service not found")
    sb.save_restricted_users(service_id, data.get("usernames") or [])
    return {"ok": True}


@router.put("/api/services/{service_id}/fields")
def api_save_fields(service_id: int, data: dict = Body(...), request: Request = None):
    require_permission(request, "can_edit")
    _svc_or_403(service_id, request)
    fields = sb.save_fields(service_id, data.get("fields") or [])
    return {"ok": True, "fields": fields}


@router.put("/api/services/{service_id}/excel-columns")
def api_save_excel_columns(service_id: int, data: dict = Body(...), request: Request = None):
    require_permission(request, "can_edit")
    _svc_or_403(service_id, request)
    sb.save_excel_columns(service_id, data.get("columns") or [])
    return {"ok": True}


@router.put("/api/services/{service_id}/analytics-config")
def api_save_analytics_config(service_id: int, data: dict = Body(...), request: Request = None):
    require_permission(request, "can_edit")
    _svc_or_403(service_id, request)
    sb.save_analytics_config(service_id, data.get("config") or [])
    return {"ok": True}


@router.get("/api/services/{service_id}/analytics-data")
def api_analytics_data(service_id: int, request: Request):
    require_permission(request, "can_create")
    svc = _svc_or_403(service_id, request)
    return sb.compute_analytics(svc)


# ---------------------------------------------------------------- records
@router.get("/api/services/{service_id}/records")
def api_list_records(service_id: int, q: str = "", request: Request = None):
    require_permission(request, "can_create")
    _svc_or_403(service_id, request)
    return {"records": sb.list_records(service_id, q)}


@router.post("/api/services/{service_id}/records")
def api_create_record(service_id: int, data: dict = Body(...), request: Request = None):
    require_permission(request, "can_create")
    _svc_or_403(service_id, request)
    return sb.create_record(service_id, data.get("data") or {})


@router.get("/api/services/{service_id}/records/{record_id}")
def api_get_record(service_id: int, record_id: int, request: Request):
    require_permission(request, "can_create")
    _svc_or_403(service_id, request)
    rec = sb.get_record(service_id, record_id)
    if not rec:
        raise HTTPException(404, "Record not found")
    return rec


@router.put("/api/services/{service_id}/records/{record_id}")
def api_update_record(service_id: int, record_id: int, data: dict = Body(...), request: Request = None):
    require_permission(request, "can_edit")
    _svc_or_403(service_id, request)
    rec = sb.update_record(service_id, record_id, data.get("data") or {})
    if not rec:
        raise HTTPException(404, "Record not found")
    return rec


@router.delete("/api/services/{service_id}/records/{record_id}")
def api_delete_record(service_id: int, record_id: int, request: Request):
    require_permission(request, "can_delete")
    _svc_or_403(service_id, request)
    if not sb.delete_record(service_id, record_id):
        raise HTTPException(404, "Record not found")
    return {"ok": True}


# ---------------------------------------------------------------- trash
@router.get("/api/services/{service_id}/trash")
def api_list_trash(service_id: int, request: Request):
    require_permission(request, "can_create")
    _svc_or_403(service_id, request)
    return {"records": sb.list_trash(service_id)}


@router.post("/api/services/{service_id}/records/{record_id}/restore")
def api_restore_record(service_id: int, record_id: int, request: Request):
    require_permission(request, "can_delete")
    _svc_or_403(service_id, request)
    if not sb.restore_record(service_id, record_id):
        raise HTTPException(404, "Record not in trash")
    return {"ok": True}


@router.delete("/api/services/{service_id}/records/{record_id}/purge")
def api_purge_record(service_id: int, record_id: int, request: Request):
    require_permission(request, "can_purge")
    _svc_or_403(service_id, request)
    if not sb.purge_record(service_id, record_id):
        raise HTTPException(404, "Record not in trash")
    return {"ok": True}


@router.post("/api/services/{service_id}/trash/empty")
def api_empty_trash(service_id: int, request: Request):
    require_permission(request, "can_purge")
    _svc_or_403(service_id, request)
    n = sb.empty_trash(service_id)
    return {"ok": True, "purged": n}


# ---------------------------------------------------------------- attachments
@router.get("/api/services/{service_id}/records/{record_id}/attachments")
def api_list_attachments(service_id: int, record_id: int, request: Request):
    require_permission(request, "can_create")
    _svc_or_403(service_id, request)
    return {"attachments": sb.list_attachments(record_id)}


@router.post("/api/services/{service_id}/records/{record_id}/attachments")
def api_add_attachment(service_id: int, record_id: int, data: dict = Body(...), request: Request = None):
    require_permission(request, "can_edit")
    _svc_or_403(service_id, request)
    if not sb.get_record(service_id, record_id):
        raise HTTPException(404, "Record not found")
    username, _role = _requester(request)
    try:
        att = sb.add_attachment(record_id, data.get("b64") or "", data.get("filename") or "", username)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, **att}


@router.get("/api/services/{service_id}/attachments/{attachment_id}/download")
def api_download_attachment(service_id: int, attachment_id: int, request: Request):
    require_permission(request, "can_create")
    _svc_or_403(service_id, request)
    att = sb.get_attachment(attachment_id)
    if not att:
        raise HTTPException(404, "Attachment not found")
    import os
    if not att["stored_path"] or not os.path.exists(att["stored_path"]):
        raise HTTPException(404, "That file is missing from disk")
    with open(att["stored_path"], "rb") as f:
        content = f.read()
    return Response(
        content=content, media_type=att["mime_type"] or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{att["filename"]}"'},
    )


@router.delete("/api/services/{service_id}/attachments/{attachment_id}")
def api_delete_attachment(service_id: int, attachment_id: int, request: Request):
    require_permission(request, "can_edit")
    _svc_or_403(service_id, request)
    if not sb.delete_attachment(attachment_id):
        raise HTTPException(404, "Attachment not found")
    return {"ok": True}


# ---------------------------------------------------------------- bulk import
@router.post("/api/services/{service_id}/import")
def api_import_records(service_id: int, data: dict = Body(...), request: Request = None):
    require_permission(request, "can_import")
    svc = _svc_or_403(service_id, request)
    import base64 as _b64
    b64 = data.get("b64") or ""
    header, _, payload = b64.partition(",")
    try:
        file_bytes = _b64.b64decode(payload or b64)
    except Exception:
        raise HTTPException(400, "Could not read that file")
    try:
        result = sb.import_records_from_excel(svc, file_bytes)
    except Exception as e:
        raise HTTPException(400, f"Could not read that spreadsheet: {e}")
    return {"ok": True, **result}


# ---------------------------------------------------------------- board / expiry / map
@router.get("/api/services/{service_id}/board")
def api_get_board(service_id: int, request: Request):
    require_permission(request, "can_create")
    svc = _svc_or_403(service_id, request)
    return sb.compute_board(svc)


@router.get("/api/services/{service_id}/expiring")
def api_get_expiring(service_id: int, days: int = 30, request: Request = None):
    require_permission(request, "can_create")
    svc = _svc_or_403(service_id, request)
    return sb.compute_expiring(svc, within_days=days)


@router.get("/api/services/{service_id}/map")
def api_get_map(service_id: int, request: Request):
    require_permission(request, "can_create")
    svc = _svc_or_403(service_id, request)
    return sb.compute_map_points(svc)


@router.get("/api/services/{service_id}/print-data/{record_id}")
def api_print_data(service_id: int, record_id: int, request: Request):
    require_permission(request, "can_print")
    svc = _svc_or_403(service_id, request)
    rec = sb.get_record(service_id, record_id)
    if not rec:
        raise HTTPException(404, "Record not found")
    return {"ok": True, "fields": sb.formatted_fields(svc, rec)}


# ---------------------------------------------------------------- Excel export
@router.get("/api/services/{service_id}/export")
def api_export_excel(service_id: int, request: Request):
    require_permission(request, "can_export")
    svc = _svc_or_403(service_id, request)
    xlsx_bytes = sb.build_excel(svc)
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", svc["name"]).strip() or f"Service_{service_id}"
    return Response(
        content=xlsx_bytes, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.xlsx"'},
    )


# ---------------------------------------------------------------- print template
@router.get("/api/services/{service_id}/print-template")
def api_get_print_template(service_id: int, request: Request):
    require_permission(request, "can_print")
    svc = _svc_or_403(service_id, request)
    return svc["print_template"]


@router.get("/api/services/{service_id}/print-template/default")
def api_get_default_print_template(service_id: int, request: Request):
    require_permission(request, "can_print")
    svc = _svc_or_403(service_id, request)
    return svc["print_template_default"]


@router.put("/api/services/{service_id}/print-template")
def api_update_print_template(service_id: int, data: dict = Body(...), request: Request = None):
    require_permission(request, "can_print")
    _svc_or_403(service_id, request)
    if "boxes" not in data:
        raise HTTPException(400, "Template must include a 'boxes' list")
    sb.save_print_template(service_id, data)
    return {"ok": True}


@router.post("/api/services/{service_id}/print-template/set-default")
def api_set_default_print_template(service_id: int, request: Request):
    require_permission(request, "can_print")
    _svc_or_403(service_id, request)
    sb.save_print_template_as_default(service_id)
    return {"ok": True}


@router.get("/api/services/{service_id}/print-template/history")
def api_list_print_history(service_id: int, request: Request):
    require_permission(request, "can_print")
    _svc_or_403(service_id, request)
    return {"history": sb.load_print_history(service_id)}


@router.post("/api/services/{service_id}/print-template/history")
def api_save_print_history(service_id: int, data: dict = Body(...), request: Request = None):
    require_permission(request, "can_print")
    _svc_or_403(service_id, request)
    tpl = data.get("template")
    if not tpl or "boxes" not in tpl:
        raise HTTPException(400, "Missing template data to save")
    entry = sb.add_print_history_entry(service_id, data.get("name"), tpl)
    return {"ok": True, **entry}


@router.get("/api/services/{service_id}/print-template/history/{entry_id}")
def api_get_print_history_entry(service_id: int, entry_id: int, request: Request):
    require_permission(request, "can_print")
    _svc_or_403(service_id, request)
    entry = sb.get_print_history_entry(service_id, entry_id)
    if not entry:
        raise HTTPException(404, "That saved layout no longer exists")
    return entry["data"]


@router.post("/api/services/{service_id}/print-template/history/{entry_id}/restore")
def api_restore_print_history_entry(service_id: int, entry_id: int, request: Request):
    require_permission(request, "can_print")
    _svc_or_403(service_id, request)
    entry = sb.get_print_history_entry(service_id, entry_id)
    if not entry:
        raise HTTPException(404, "That saved layout no longer exists")
    sb.save_print_template(service_id, entry["data"])
    return {"ok": True}


@router.delete("/api/services/{service_id}/print-template/history/{entry_id}")
def api_delete_print_history_entry(service_id: int, entry_id: int, request: Request):
    require_permission(request, "can_print")
    _svc_or_403(service_id, request)
    if not sb.delete_print_history_entry(service_id, entry_id):
        raise HTTPException(404, "That saved layout no longer exists")
    return {"ok": True}


@router.get("/api/services/{service_id}/print-pdf/{record_id}")
def api_print_pdf(service_id: int, record_id: int, request: Request):
    require_permission(request, "can_print")
    svc = _svc_or_403(service_id, request)
    rec = sb.get_record(service_id, record_id)
    if not rec:
        raise HTTPException(404, "Record not found")
    try:
        pdf_bytes = sb.build_pdf(svc, rec)
    except Exception as e:
        raise HTTPException(500, f"Could not generate the PDF: {e}")
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="Record_{record_id}.pdf"'},
    )


@router.get("/api/services/{service_id}/print-pdf-batch")
def api_print_pdf_batch(service_id: int, ids: str, request: Request):
    require_permission(request, "can_print")
    svc = _svc_or_403(service_id, request)
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
        for i, rid in enumerate(id_list, start=1):
            rec = sb.get_record(service_id, rid)
            if not rec:
                continue
            try:
                pdf_bytes = sb.build_pdf(svc, rec, batch_index=i, batch_total=total)
            except Exception:
                continue
            name = f"Record_{rid}.pdf"
            n = 2
            while name in used_names:
                name = f"Record_{rid}_{n}.pdf"; n += 1
            used_names.add(name)
            zf.writestr(name, pdf_bytes)
            added += 1
    if added == 0:
        raise HTTPException(404, "None of the given records could be found")
    safe_name = re.sub(r'[\\/:*?"<>|]', "_", svc["name"]).strip() or f"Service_{service_id}"
    return Response(
        content=zip_buf.getvalue(), media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}_Batch_Print.zip"'},
    )
