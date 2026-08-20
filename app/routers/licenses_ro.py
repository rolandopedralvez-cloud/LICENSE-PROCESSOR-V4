"""
app/routers/licenses_ro.py — SQLAlchemy port of the two read-only license
endpoints from main.py: GET /api/licenses (list/search) and
GET /api/licenses/{id} (single record + payments).

"_ro" = read-only. The write endpoints (POST/PUT/DELETE /api/licenses...)
are NOT ported here yet — they still live in main.py and require
require_permission()/log_activity(), which depend on main.py's in-memory
TOKENS/auth machinery. Porting those is the next step after this one (see
MODERNIZATION_PLAN.md step 6) and should reuse the same auth dependency,
not a new one — do not duplicate the permission system.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models.license import License, Payment

router = APIRouter(tags=["licenses"])

_LIST_FIELDS = [
    "id", "license_no", "licensee", "site_name", "brgy", "town", "province",
    "class_of_station", "tech", "validity_from", "validity_to",
    "license_status", "status", "or_no", "or_date", "or_amount",
    "created_at", "updated_at",
]


@router.get("/api/licenses")
def list_licenses(
    q: str = Query("", description="search text"),
    province: str = "",
    licensee: str = "",
    status: str = "",
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    query = db.query(License).filter(License.deleted_at.is_(None))

    if q:
        like = f"%{q}%"
        search_cols = [
            License.license_no, License.site_no, License.site_name, License.brgy,
            License.town, License.province, License.licensee, License.tech,
            License.or_no, License.or_date,
        ]
        query = query.filter(or_(*(col.like(like) for col in search_cols)))
    if province:
        query = query.filter(License.province == province)
    if licensee:
        query = query.filter(License.licensee == licensee)
    if status:
        query = query.filter(License.license_status == status)

    total = query.count()
    rows = query.order_by(License.id).limit(limit).offset(offset).all()

    results = [{f: getattr(r, f) for f in _LIST_FIELDS} for r in rows]
    return {"total": total, "count": len(results), "limit": limit, "offset": offset, "results": results}


@router.get("/api/licenses/{lic_id}")
def get_license(lic_id: int, db: Session = Depends(get_db)):
    row = db.get(License, lic_id)
    if not row:
        raise HTTPException(404, "License not found")
    license_dict = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    payments = db.query(Payment).filter(Payment.license_id == lic_id).order_by(Payment.year).all()
    payments_out = [{c.name: getattr(p, c.name) for c in p.__table__.columns} for p in payments]
    return {"license": license_dict, "payments": payments_out}
