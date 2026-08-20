"""
app/routers/meta.py — SQLAlchemy port of the read-only dropdown/stats/
history endpoints from main.py: /api/meta, /api/stats,
/api/licenses/{id}/history.

Ported first (see MODERNIZATION_PLAN.md step 5/6) because they are pure
reads with no auth requirement and no write side effects — the lowest-risk
place to prove the SQLAlchemy-session pattern end to end before touching
anything that mutates data or checks permissions.

Behavior is intended to match the original main.py routes exactly. The
main.py versions of these three routes should be considered superseded by
this router once it is mounted (see app/main.py) — do not maintain both.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import distinct, func
from sqlalchemy.orm import Session
from sqlalchemy import inspect as sa_inspect

from app.deps import get_db
from app.database import engine
from app.models.license import License, Payment

router = APIRouter(tags=["meta"])


def _distinct_values(db: Session, column):
    rows = (
        db.query(distinct(column))
        .filter(column.isnot(None), column != "")
        .order_by(column)
        .all()
    )
    return [r[0] for r in rows]


@router.get("/api/meta")
def meta(db: Session = Depends(get_db)):
    licenses_columns = [c["name"] for c in sa_inspect(engine).get_columns("licenses")]
    return {
        "provinces": _distinct_values(db, License.province),
        "licensees": _distinct_values(db, License.licensee),
        "statuses": _distinct_values(db, License.license_status),
        "classes": _distinct_values(db, License.class_of_station),
        "techs": _distinct_values(db, License.tech),
        "columns": licenses_columns,
    }


@router.get("/api/licenses/{lic_id}/history")
def history(lic_id: int, db: Session = Depends(get_db)):
    chain = []
    seen = set()
    cur_id = lic_id
    while cur_id and cur_id not in seen:
        seen.add(cur_id)
        row = db.get(License, cur_id)
        if not row:
            break
        chain.append({
            "id": row.id,
            "license_no": row.license_no,
            "rsl_date": row.rsl_date,
            "validity_from": row.validity_from,
            "validity_to": row.validity_to,
            "new_form_no": row.new_form_no,
            "old_form_no": row.old_form_no,
            "renewed_from": row.renewed_from,
        })
        cur_id = row.renewed_from

    kids = (
        db.query(License)
        .filter(License.renewed_from == lic_id)
        .all()
    )
    chain = list(reversed(chain))  # oldest first
    return {
        "chain": chain,
        "newer": [
            {
                "id": k.id,
                "license_no": k.license_no,
                "rsl_date": k.rsl_date,
                "validity_from": k.validity_from,
                "validity_to": k.validity_to,
                "new_form_no": k.new_form_no,
                "old_form_no": k.old_form_no,
                "renewed_from": k.renewed_from,
            }
            for k in kids
        ],
    }


@router.get("/api/stats")
def stats(db: Session = Depends(get_db)):
    def grp(column):
        rows = (
            db.query(column, func.count())
            .filter(License.deleted_at.is_(None))
            .group_by(column)
            .order_by(func.count().desc())
            .all()
        )
        return {r[0]: r[1] for r in rows}

    return {
        "total_licenses": db.query(func.count(License.id)).filter(License.deleted_at.is_(None)).scalar(),
        "total_payments": db.query(func.count(Payment.id)).scalar(),
        "trash_count": db.query(func.count(License.id)).filter(License.deleted_at.isnot(None)).scalar(),
        "by_province": grp(License.province),
        "by_licensee": grp(License.licensee),
        "by_status": grp(License.license_status),
    }
