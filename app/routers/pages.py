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


@router.get("/app/licenses/results")
def app_licenses_results(request: Request, q: str = "", _user=Depends(require_login), db: Session = Depends(get_db)):
    query = db.query(License).filter(License.deleted_at.is_(None))
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                License.licensee.ilike(like),
                License.license_no.ilike(like),
                License.site_name.ilike(like),
                License.or_no.ilike(like),
            )
        )
    results = query.order_by(License.id.desc()).limit(100).all()
    return templates.TemplateResponse(
        request, "app/_license_rows.html", {"results": results}
    )


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
    ]),
    ("Radio / Technical", [
        ("class_of_station", "Class of Station"), ("nature_of_service", "Nature of Service"),
        ("callsign", "Callsign"), ("hours", "Hours"), ("tech", "Technology"),
        ("freq1", "Frequency 1"), ("freq2", "Frequency 2"), ("power", "Power"),
        ("capacity", "Capacity"),
    ]),
    ("Validity / OR", [
        ("validity_from", "Validity From"), ("validity_to", "Validity To"),
        ("or_no", "OR No."), ("or_date", "OR Date"), ("or_amount", "OR Amount"),
    ]),
    ("Misc", [
        ("license_status", "License Status"), ("case_number", "Case Number"),
        ("other_remarks", "Other Remarks"),
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
