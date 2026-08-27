"""app/routers/pages.py — "/" (existing index.html, unchanged) plus the
HTMX/Jinja2/Tailwind UI added alongside it. Two layers here:

  /search-ui, /search-ui/results  — the original minimal search demo
      (step 6 of MODERNIZATION_PLAN.md).
  /app, /app/login, /app/licenses/*  — the fuller HTMX "mini app":
      login, search, view/edit, create, delete, print. Reuses the SAME
      login/session as index.html (same localStorage keys, same TOKENS
      dict server-side) — one account works on both UIs.

None of this touches or replaces index.html. It's still served at "/",
unchanged, and remains the only place a few things live for now (users,
import, analytics/pivot, batch renew, location check, scan review,
settings/backup) — see NOTES.md for what's ported here vs. still only in
the classic UI.

SECURITY NOTE: every route below that renders real license data now
requires a valid session (via app.deps.require_login), the same way every
/api/* route already does via the middleware in app/main.py. The very
first version of /search-ui did NOT check auth (it predates any
write/detail views, when "read-only, no permission required" briefly
looked equivalent to "no auth required" — main.py's own /api/meta and
/api/stats really do skip auth, so it was an easy road to accidentally
generalize past what's true for the middleware-guarded license data
routes). Fixed here before adding /app/licenses/{id}, which would
otherwise have exposed full record detail to anyone with the URL.
"""
import os
from pathlib import Path

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.deps import get_db, require_login
from app.models.license import License

router = APIRouter(tags=["pages"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/", response_class=HTMLResponse)
def root():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return HTMLResponse(
        "<h2>Backend running.</h2><p>Put index.html in this folder, "
        "or visit <a href='/docs'>/docs</a>.</p>")


# ---------------------------------------------------------------- /search-ui (minimal demo)
@router.get("/search-ui")
def search_page(request: Request, _user=Depends(require_login), db: Session = Depends(get_db)):
    results = (
        db.query(License)
        .filter(License.deleted_at.is_(None))
        .order_by(License.id)
        .limit(50)
        .all()
    )
    return templates.TemplateResponse(
        request, "licenses/search.html", {"results": results, "q": ""}
    )


@router.get("/search-ui/results")
def search_results(request: Request, q: str = "", _user=Depends(require_login), db: Session = Depends(get_db)):
    query = db.query(License).filter(License.deleted_at.is_(None))
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                License.licensee.ilike(like),
                License.license_no.ilike(like),
                License.site_name.ilike(like),
            )
        )
    results = query.order_by(License.id).limit(50).all()
    return templates.TemplateResponse(
        request, "licenses/_results.html", {"results": results}
    )


# ---------------------------------------------------------------- /app (fuller mini app)
@router.get("/app/login")
def app_login(request: Request):
    return templates.TemplateResponse(request, "app/login.html", {})


@router.get("/app")
def app_home(request: Request):
    """The list/search shell. Deliberately renders NO license data itself
    (unlike /search-ui) -- it loads results via hx-trigger="load" against
    the auth-checked /app/licenses/results endpoint instead. That way a
    logged-out visitor hitting /app directly sees an empty shell (whose
    only content is a search box), not real records; app/_shell.html's
    ntcRequireAuth() then bounces them to /app/login client-side, and the
    results fetch itself would 401 either way."""
    return templates.TemplateResponse(request, "app/licenses_list.html", {})


# Columns the results table is allowed to sort by. Whitelisted deliberately:
# the sort key arrives from the browser and is used to pick a column, so it
# must never be taken as free text.
SORTABLE = {
    "license_no": License.license_no,
    "licensee": License.licensee,
    "site_name": License.site_name,
    "province": License.province,
    "status": License.license_status,
    "id": License.id,
}

PAGE_SIZE = 100


@router.get("/app/licenses/results")
def app_licenses_results(
    request: Request,
    q: str = "",
    province: str = "",
    status: str = "",
    licensee: str = "",
    sort: str = "id",
    dir: str = "desc",
    offset: int = 0,
    partial: str = "",
    _user=Depends(require_login),
    db: Session = Depends(get_db),
):
    """Search results for the dashboard.

    Three things changed here, all of which the screen was getting wrong:

    1. It searched only 4 columns (licensee / license_no / site_name / or_no)
       while /api/licenses searched 10 -- so typing a municipality or a
       barangay in the main search box found nothing, even though the data
       was right there. Same field list as the API now.
    2. It returned a bare .limit(100) with no total and no paging, and the
       page showed no count -- so a search matching 400 records looked
       exactly like one matching 100, and a clerk could conclude a station
       wasn't registered when it was. The total is returned now and the
       template shows "Showing X of Y" plus a Load More button.
    3. There was no sorting or filtering at all, even though the province /
       status / licensee filters already existed on the JSON API.
    """
    query = db.query(License).filter(License.deleted_at.is_(None))
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                License.license_no.ilike(like),
                License.site_no.ilike(like),
                License.site_name.ilike(like),
                License.brgy.ilike(like),
                License.town.ilike(like),
                License.province.ilike(like),
                License.licensee.ilike(like),
                License.tech.ilike(like),
                License.or_no.ilike(like),
                License.or_date.ilike(like),
            )
        )
    if province:
        query = query.filter(License.province == province)
    if status:
        query = query.filter(License.license_status == status)
    if licensee:
        query = query.filter(License.licensee == licensee)

    total = query.count()

    col = SORTABLE.get(sort, License.id)
    query = query.order_by(col.asc() if dir == "asc" else col.desc())

    offset = max(0, offset)
    results = query.limit(PAGE_SIZE).offset(offset).all()

    shown_to = offset + len(results)
    ctx = {
        "results": results,
        "total": total,
        "offset": offset,
        "shown_to": shown_to,
        "has_more": shown_to < total,
        "next_offset": shown_to,
        "q": q, "province": province, "status": status, "licensee": licensee,
        "sort": sort, "dir": dir,
    }
    # "partial" = the Load More button asking for the NEXT page: return just
    # the extra rows, which htmx appends, instead of the whole table again.
    tpl = "app/_license_row_items.html" if partial else "app/_license_rows.html"
    return templates.TemplateResponse(request, tpl, ctx)


# A curated subset of `licenses` columns for the new form -- not all 63+.
# Grouped for a usable form; the classic UI at "/" still has every single
# field for the long tail this doesn't cover yet (see NOTES.md).
FORM_SECTIONS = [
    ("Identity", [
        ("status", "Status"), ("license_no", "License No."), ("rsl_date", "RSL Date"),
        ("licensee", "Licensee"), ("to_operate", "To Operate"),
    ]),
    ("Location", [
        ("site_no", "Site No."), ("site_name", "Site Name"), ("address", "Address"),
        ("brgy", "Barangay"), ("town", "Town/City"), ("province", "Province"),
        ("region", "Region"), ("zip_code", "ZIP Code"), ("psgc", "PSGC"),
        # Coordinates, in degrees/minutes/seconds (same split as the classic UI) --
        # these also drive the pin map below the form: dragging/placing a pin
        # fills these in automatically, and typing in these updates the pin.
        ("elong_deg", "E Long °"), ("elong_min", "E Long ′"), ("elong_sec", "E Long ″"),
        ("nlat_deg", "N Lat °"), ("nlat_min", "N Lat ′"), ("nlat_sec", "N Lat ″"),
    ]),
    ("Radio / Technical", [
        ("class_of_station", "Class of Station"), ("nature_of_service", "Nature of Service"),
        ("callsign", "Callsign"), ("hours", "Hours"), ("tech", "Technology"),
        ("freq1", "Frequency 1"), ("freq2", "Frequency 2"), ("freq3", "Frequency 3"),
        ("freq4", "Frequency 4"), ("freq_range", "Frequency Range"), ("pol", "Polarization"),
        ("bw_emission", "BW & Emission"), ("power", "Power"), ("capacity", "Capacity"),
        ("points_of_comm", "Points of Communication"), ("config", "Config/Channel"),
        ("total", "Total"),
    ]),
    # Antenna details -- were missing from this form even though the RSL
    # certificate (see the Live/Print Preview) shows them; restored here so
    # they're editable, not just display-only on the certificate.
    ("Antenna", [
        ("directive", "Directive"), ("hag", "HAG"), ("gain", "Gain"), ("type", "Type"),
    ]),
    ("Equipment", [
        ("make_model", "Make Type & Model"), ("serial_no", "Serial No."),
        ("new_form_no", "New Form No."), ("old_form_no", "Old Form No."),
        ("old_date", "Old Date"),
    ]),
    ("Validity / OR", [
        ("validity_from", "Validity From"), ("validity_to", "Validity To"),
        ("or_no", "OR No."), ("or_date", "OR Date"), ("or_amount", "OR Amount"),
    ]),
    ("Misc", [
        ("license_status", "License Status"), ("case_number", "Case Number"),
        ("other_remarks", "Other Remarks"), ("other_reference", "Other Reference"),
        ("dst", "DST"), ("signatory", "Signatory"), ("designation", "Designation"),
        ("processor", "Processor"),
    ]),
]


@router.get("/app/licenses/new")
def app_license_new(request: Request, _user=Depends(require_login)):
    return templates.TemplateResponse(
        request, "app/license_form.html",
        {"sections": FORM_SECTIONS, "license": None, "lic_id": None},
    )


@router.get("/app/licenses/{lic_id}")
def app_license_detail(request: Request, lic_id: int, _user=Depends(require_login), db: Session = Depends(get_db)):
    row = db.get(License, lic_id)
    if not row or row.deleted_at:
        raise HTTPException(404, "License not found")
    license_dict = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    return templates.TemplateResponse(
        request, "app/license_form.html",
        {"sections": FORM_SECTIONS, "license": license_dict, "lic_id": lic_id},
    )


@router.get("/app/licenses/{lic_id}/print-preview")
def app_license_print_preview(request: Request, lic_id: int, _user=Depends(require_login), db: Session = Depends(get_db)):
    """The built-in Live Preview / Design mode / PDF export page -- see
    app/legacy/print_builtin.py. Purely additive next to the existing
    Excel/Word print flow (app/routers/print.py), not a replacement."""
    row = db.get(License, lic_id)
    if not row or row.deleted_at:
        raise HTTPException(404, "License not found")
    return templates.TemplateResponse(
        request, "app/print_preview.html",
        {"lic_id": lic_id, "license_no": row.license_no, "licensee": row.licensee},
    )


# ---------------------------------------------------------------- /app extras
# Page shells for the rest of the classic UI's features, ported over to the
# same AdminLTE-style look. Every one of these is JUST a template that reads
# from / writes to the SAME /api/* endpoints the classic UI already uses
# (via window.ntcFetch, same as license_form.html does for create/edit/
# delete) -- no new backend routes, no second implementation of any of
# this logic. Auth here is only require_login (any signed-in user can load
# the *page*); the real permission gate for each action is still whatever
# the underlying /api/* endpoint already enforces (require_permission /
# require_super_admin in app/core.py) -- a user without a permission will
# just get a 403 back from the fetch call, same as clicking a
# permission-gated button in the classic UI.

@router.get("/app/batch-renew")
def app_batch_renew(request: Request, _user=Depends(require_login)):
    return templates.TemplateResponse(request, "app/batch_renew.html", {})


@router.get("/app/batch-review")
def app_batch_review(request: Request, _user=Depends(require_login)):
    """Batch Review -- the 'locked' multi-record review/print screen reached
    from Batch Renew. The list of record ids to review travels via
    sessionStorage (set by batch_renew.html just before it navigates here),
    not a query string, so this route needs nothing from the server beyond
    the shell and the shared FORM_SECTIONS the edit form already uses."""
    return templates.TemplateResponse(
        request, "app/batch_review.html", {"sections": FORM_SECTIONS},
    )


@router.get("/app/import")
def app_import(request: Request, _user=Depends(require_login)):
    return templates.TemplateResponse(request, "app/import.html", {})


@router.get("/app/analytics")
def app_analytics(request: Request, _user=Depends(require_login)):
    return templates.TemplateResponse(request, "app/analytics.html", {})


@router.get("/app/location-check")
def app_location_check(request: Request, _user=Depends(require_login)):
    return templates.TemplateResponse(request, "app/location_check.html", {})


@router.get("/app/scan")
def app_scan(request: Request, _user=Depends(require_login)):
    return templates.TemplateResponse(request, "app/scan.html", {"scan_id": None})


@router.get("/app/scan/{scan_id}")
def app_scan_detail(request: Request, scan_id: int, _user=Depends(require_login)):
    return templates.TemplateResponse(request, "app/scan.html", {"scan_id": scan_id})


@router.get("/app/trash")
def app_trash(request: Request, _user=Depends(require_login)):
    return templates.TemplateResponse(request, "app/trash.html", {})


@router.get("/app/users")
def app_users(request: Request, _user=Depends(require_login)):
    return templates.TemplateResponse(request, "app/users.html", {})


@router.get("/app/settings")
def app_settings(request: Request, _user=Depends(require_login)):
    return templates.TemplateResponse(request, "app/settings.html", {})


# ---------------------------------------------------------------- Other Services
# See app/legacy/services_builtin.py -- a separate, generic multi-service
# system that sits alongside Telco RSL licensing without touching it. Every
# page here is just a shell that reads/writes /api/services/* (same
# window.ntcFetch pattern as everything else in this file).

@router.get("/app/services")
def app_services_list(request: Request, _user=Depends(require_login)):
    return templates.TemplateResponse(request, "app/services_list.html", {})


@router.get("/app/services/{service_id}/records")
def app_service_records(request: Request, service_id: int, _user=Depends(require_login)):
    return templates.TemplateResponse(request, "app/service_records.html", {"service_id": service_id})


@router.get("/app/services/{service_id}/design")
def app_service_design(request: Request, service_id: int, _user=Depends(require_login)):
    """The field designer -- arrange this service's custom input fields on
    a canvas (add / drag / resize / rename / retype), same drag-to-place
    idea as the Telco print Design mode. record_id is None here."""
    return templates.TemplateResponse(
        request, "app/service_form.html", {"service_id": service_id, "record_id": None, "start_in_design": True},
    )


@router.get("/app/services/{service_id}/records/new")
def app_service_record_new(request: Request, service_id: int, _user=Depends(require_login)):
    return templates.TemplateResponse(
        request, "app/service_form.html", {"service_id": service_id, "record_id": None, "start_in_design": False},
    )


@router.get("/app/services/{service_id}/records/{record_id}")
def app_service_record_edit(request: Request, service_id: int, record_id: int, _user=Depends(require_login)):
    return templates.TemplateResponse(
        request, "app/service_form.html", {"service_id": service_id, "record_id": record_id, "start_in_design": False},
    )


@router.get("/app/services/{service_id}/records/{record_id}/print-preview")
def app_service_print_preview(request: Request, service_id: int, record_id: int, _user=Depends(require_login)):
    from app.legacy import services_builtin as sb
    svc = sb.get_service(service_id)
    return templates.TemplateResponse(
        request, "app/service_print_preview.html",
        {"service_id": service_id, "record_id": record_id, "service_name": svc["name"] if svc else None},
    )


@router.get("/app/services/{service_id}/analytics")
def app_service_analytics(request: Request, service_id: int, _user=Depends(require_login)):
    return templates.TemplateResponse(request, "app/service_analytics.html", {"service_id": service_id})


@router.get("/app/services/{service_id}/trash")
def app_service_trash(request: Request, service_id: int, _user=Depends(require_login)):
    return templates.TemplateResponse(request, "app/service_trash.html", {"service_id": service_id})


@router.get("/app/services/{service_id}/import")
def app_service_import(request: Request, service_id: int, _user=Depends(require_login)):
    return templates.TemplateResponse(request, "app/service_import.html", {"service_id": service_id})


@router.get("/app/services/{service_id}/board")
def app_service_board(request: Request, service_id: int, _user=Depends(require_login)):
    return templates.TemplateResponse(request, "app/service_board.html", {"service_id": service_id})


@router.get("/app/services/{service_id}/map")
def app_service_map(request: Request, service_id: int, _user=Depends(require_login)):
    return templates.TemplateResponse(request, "app/service_map.html", {"service_id": service_id})
