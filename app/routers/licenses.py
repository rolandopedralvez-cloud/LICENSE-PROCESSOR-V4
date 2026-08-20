"""app/routers/licenses.py — /api/licenses*, history, location-check,
batch/renew, payments. Moved verbatim from main.py; still raw sqlite3
except for the handful of endpoints ported to SQLAlchemy in step 5 (see
bottom of this file / NOTES.md)."""
import math as _math
from datetime import datetime  # NOTE: _add_one_year() below shadows this with its
                                 # own local `import datetime` (the module, not the
                                 # class) -- matches main.py's original code exactly,
                                 # where the same shadowing trick was used deliberately.
from fastapi import APIRouter, HTTPException, Body, Query, Request

from app.config import DB
from app.core import (
    get_conn, cols, clean_payload, role_for, require_permission, log_activity,
    _diff_summary, PROTECTED, _dms_to_dec,
)

router = APIRouter(tags=["licenses"])

# NOTE: /api/licenses/{id}/history, GET /api/licenses (list/search), and
# GET /api/licenses/{id} used to live here (moved verbatim from main.py) but
# have been superseded by the SQLAlchemy versions in
# app/routers/meta.py (history) and app/routers/licenses_ro.py (list/get) —
# ported in step 5/6 of MODERNIZATION_PLAN.md as the lowest-risk read-only
# proof of the SQLAlchemy pattern. Removed here to avoid two competing
# implementations of the same route. The write endpoints below (POST/PUT/
# DELETE) are UNCHANGED and still the authoritative, only implementation —
# porting those to SQLAlchemy + a shared auth dependency is the next step.

# ---------------------------------------------------------------- create
@router.post("/api/licenses")
def create_license(data: dict = Body(...), request: Request = None):
    require_permission(request, "can_create")
    conn = get_conn()
    payload = clean_payload(conn, "licenses", data)
    if not payload:
        conn.close(); raise HTTPException(400, "No valid fields supplied")
    fields = list(payload.keys())
    sql = (f"INSERT INTO licenses ({','.join(fields)}) "
           f"VALUES ({','.join('?' * len(fields))})")
    cur = conn.execute(sql, [payload[f] for f in fields])
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    log_activity(request, "create", license_id=new_id, license_no=payload.get("license_no"),
                 detail="New record created" + (f" (renewed/modified from #{payload['renewed_from']})" if payload.get("renewed_from") else ""))
    return {"ok": True, "id": new_id}

# ---------------------------------------------------------------- update
@router.put("/api/licenses/{lic_id}")
def update_license(lic_id: int, data: dict = Body(...), request: Request = None):
    require_permission(request, "can_edit")
    conn = get_conn()
    old_row = conn.execute("SELECT * FROM licenses WHERE id = ?", (lic_id,)).fetchone()
    if not old_row:
        conn.close(); raise HTTPException(404, "License not found")
    old_dict = dict(old_row)
    payload = clean_payload(conn, "licenses", data)
    if not payload:
        conn.close(); raise HTTPException(400, "No valid fields supplied")
    payload["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sets = ", ".join(f"{f} = ?" for f in payload)
    conn.execute(f"UPDATE licenses SET {sets} WHERE id = ?",
                 list(payload.values()) + [lic_id])
    conn.commit(); conn.close()
    log_activity(request, "edit", license_id=lic_id, license_no=old_dict.get("license_no"),
                 detail=_diff_summary(old_dict, payload))
    return {"ok": True, "id": lic_id}

# ---------------------------------------------------------------- delete (to Trash) + Trash bin
@router.delete("/api/licenses/{lic_id}")
def delete_license(lic_id: int, request: Request):
    """Soft delete: move the record to the Trash (recoverable)."""
    require_permission(request, "can_delete")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    row = conn.execute("SELECT license_no FROM licenses WHERE id = ?", (lic_id,)).fetchone()
    cur = conn.execute(
        "UPDATE licenses SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
        (now, lic_id))
    conn.commit(); conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "License not found")
    log_activity(request, "delete", license_id=lic_id, license_no=row["license_no"] if row else None,
                 detail="Moved to Trash")
    return {"ok": True, "trashed": lic_id}


# ---------------------------------------------------------------- LOCATION CHECK (find likely-wrong coordinates)
import math as _math

# Loose sanity box for Region II, Philippines — anything outside this is
# almost certainly a data-entry error (wrong field, swapped digits, etc.)
REGION2_LAT_MIN, REGION2_LAT_MAX = 15.5, 21.5
REGION2_LNG_MIN, REGION2_LNG_MAX = 120.5, 122.8

def _haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    p1, p2 = _math.radians(lat1), _math.radians(lat2)
    dp = _math.radians(lat2 - lat1)
    dl = _math.radians(lng2 - lng1)
    a = _math.sin(dp/2)**2 + _math.cos(p1)*_math.cos(p2)*_math.sin(dl/2)**2
    return 2 * R * _math.asin(min(1, _math.sqrt(a)))

def _median(vals):
    s = sorted(vals)
    n = len(s)
    if n == 0: return None
    mid = n // 2
    return s[mid] if n % 2 else (s[mid-1] + s[mid]) / 2

@router.get("/api/location-check")
def location_check(radius_km: float = 5.0, request: Request = None):
    """
    Flags records whose coordinates look wrong:
      - missing: no usable coordinates at all
      - impossible: outside the loose Region II sanity box (swapped fields,
        stray digits, etc.)
      - outlier: further than `radius_km` from the median position of other
        stations in the same barangay (falls back to town, then province, if
        the barangay doesn't have enough neighbors to compare against)
    Nothing is changed — this only reports what to review.
    """
    require_permission(request, "can_location_check")
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, license_no, licensee, site_name, brgy, town, province, "
        "nlat_deg, nlat_min, nlat_sec, elong_deg, elong_min, elong_sec "
        "FROM licenses WHERE deleted_at IS NULL"
    ).fetchall()
    conn.close()

    recs = []
    for r in rows:
        lat = _dms_to_dec(r["nlat_deg"], r["nlat_min"], r["nlat_sec"]) or 0
        lng = _dms_to_dec(r["elong_deg"], r["elong_min"], r["elong_sec"]) or 0
        recs.append({
            "id": r["id"], "license_no": r["license_no"], "licensee": r["licensee"],
            "site_name": r["site_name"], "brgy": r["brgy"], "town": r["town"],
            "province": r["province"], "lat": lat, "lng": lng,
        })

    flagged = []

    # group keys, from most to least specific, for the "compare to neighbors" check
    def key_brgy(rc):    return (rc["province"] or "", rc["town"] or "", rc["brgy"] or "")
    def key_town(rc):    return (rc["province"] or "", rc["town"] or "")
    def key_province(rc):return (rc["province"] or "",)

    valid = [rc for rc in recs if rc["lat"] > 0 and rc["lng"] > 0
             and REGION2_LAT_MIN <= rc["lat"] <= REGION2_LAT_MAX
             and REGION2_LNG_MIN <= rc["lng"] <= REGION2_LNG_MAX]

    def group_medians(keyfn):
        groups = {}
        for rc in valid:
            groups.setdefault(keyfn(rc), []).append(rc)
        meds = {}
        for k, members in groups.items():
            if len(members) >= 3:   # need at least a few neighbors to trust a median
                meds[k] = (_median([m["lat"] for m in members]), _median([m["lng"] for m in members]), members)
        return meds

    brgy_meds    = group_medians(key_brgy)
    town_meds    = group_medians(key_town)
    province_meds= group_medians(key_province)

    MAX_NEIGHBORS = 40   # cap the neighbor list so provincial fallback groups stay light

    def find_group(rc):
        """Return group info + the actual neighbor stations for the tightest
        group with enough members to trust, or {} if nowhere has enough."""
        for keyfn, meds, label in ((key_brgy, brgy_meds, "barangay"), (key_town, town_meds, "town"), (key_province, province_meds, "province")):
            k = keyfn(rc)
            if k in meds:
                mlat, mlng, members = meds[k]
                others = [m for m in members if m["id"] != rc["id"]][:MAX_NEIGHBORS]
                return {
                    "group_lat": mlat, "group_lng": mlng, "group_basis": label, "group_n": len(members),
                    "group_points": [{"id": m["id"], "license_no": m["license_no"], "lat": m["lat"], "lng": m["lng"]} for m in others],
                }
        return {}

    for rc in recs:
        lat, lng = rc["lat"], rc["lng"]
        if lat <= 0 or lng <= 0:
            flagged.append({**rc, "reason": "missing", "detail": "No coordinates entered",
                             "distance_km": None, **find_group(rc)})
            continue
        if not (REGION2_LAT_MIN <= lat <= REGION2_LAT_MAX and REGION2_LNG_MIN <= lng <= REGION2_LNG_MAX):
            flagged.append({**rc, "reason": "impossible",
                             "detail": f"Coordinates fall outside Region II (lat {lat:.4f}, lng {lng:.4f}) — check for swapped or mistyped values",
                             "distance_km": None, **find_group(rc)})
            continue
        # compare to the tightest group that has enough neighbors
        group = find_group(rc)
        if not group:
            continue   # not enough neighbors anywhere to judge this one
        dist = _haversine_km(lat, lng, group["group_lat"], group["group_lng"])
        if dist > radius_km:
            flagged.append({**rc, "reason": "outlier",
                             "detail": f"{dist:.1f} km from the other {group['group_n']} station(s) in the same {group['group_basis']}",
                             "distance_km": round(dist, 1), **group})

    # worst first: impossible/missing before distance outliers, then farthest first
    order = {"impossible": 0, "missing": 0, "outlier": 1}
    flagged.sort(key=lambda f: (order.get(f["reason"], 2), -(f["distance_km"] or 0)))
    return {"count": len(flagged), "checked": len(recs), "results": flagged}
@router.post("/api/batch/renew")
def _add_one_year(iso_date):
    """'2025-06-28' -> '2026-06-28' -- used to roll a record's validity
    period forward by exactly one year on renewal (e.g. 2025-2026 becomes
    2026-2027). Falls back to Feb 28 for a Feb 29 source date landing on a
    non-leap year. Returns None for anything blank/unparseable."""
    import datetime
    if not iso_date:
        return None
    s = str(iso_date)[:10]
    try:
        y, m, d = (int(p) for p in s.split("-"))
    except Exception:
        return None
    try:
        return datetime.date(y + 1, m, d).isoformat()
    except ValueError:
        return datetime.date(y + 1, m, d - 1).isoformat()   # Feb 29 -> Feb 28

def batch_renew(data: dict = Body(...), request: Request = None):
    """
    Renew many RSLs at once with one shared Official Receipt.
      data = {
        "source_ids": [12, 15, 33, ...],
        "shared":     {"or_no":..., "or_date":..., "or_amount":...}
      }
    For each source it creates a new RENEWAL record (original kept as history):
      - carries the current New Form No. -> Old Form No., and RSL Date -> Old Date
      - applies the shared OR number / date / amount
      - RSL Date is always set to the OR Date (they're carried together)
      - Validity From/To are rolled forward one year from the source record's
        current validity dates (e.g. 2025-06-28→2026-06-27 becomes
        2026-06-28→2027-06-27), instead of being left blank
      - clears the New Form No. (set per record before printing)
    Returns the new record ids in the same order.
    """
    require_permission(request, "can_batch_renew")
    source_ids = data.get("source_ids", [])
    shared     = data.get("shared", {}) or {}
    mode       = data.get("mode") or "new"   # "new" (default) creates renewed copies
                                              # and keeps the originals as history, same
                                              # as Renew on a single record; "overwrite"
                                              # updates the same rows in place instead —
                                              # no history rows, but still shows up in the
                                              # Activity Log like any other edit
    if mode not in ("new", "overwrite"):
        mode = "new"
    if not source_ids:
        raise HTTPException(400, "No stations selected")

    SHARED_KEYS = {"or_no", "or_date", "or_amount"}
    shared = {k: v for k, v in shared.items() if k in SHARED_KEYS}

    conn = get_conn()
    writable = set(cols(conn, "licenses")) - PROTECTED
    new_ids = []
    overwritten_ids = []
    try:
        for sid in source_ids:
            row = conn.execute("SELECT * FROM licenses WHERE id = ?", (sid,)).fetchone()
            if not row:
                continue
            src = dict(row)
            rec = {k: v for k, v in src.items() if k in writable}

            rec["old_form_no"]  = src.get("new_form_no")
            rec["old_date"]     = src.get("rsl_date")
            rec["new_form_no"]  = None          # blank until the new form is issued

            # roll the validity period forward one year from what it currently
            # is, instead of leaving it blank for someone to fill in by hand
            rec["validity_from"] = _add_one_year(src.get("validity_from"))
            rec["validity_to"]   = _add_one_year(src.get("validity_to"))

            # shared batch data (one OR covers the batch)
            for k, v in shared.items():
                rec[k] = v

            # RSL Date always travels with the OR Date -- no separate entry,
            # no chance of the two disagreeing
            if shared.get("or_date"):
                rec["rsl_date"] = shared["or_date"]

            rec["status"] = "RENEWAL"
            rec["license_status"] = "RENEWAL"

            if mode == "overwrite":
                rec.pop("id", None)
                sets = ", ".join(f"{f} = ?" for f in rec)
                conn.execute(f"UPDATE licenses SET {sets} WHERE id = ?", list(rec.values()) + [sid])
                overwritten_ids.append(sid)
            else:
                rec["renewed_from"] = sid   # history link — only meaningful when a new row is made
                fields = list(rec.keys())
                sql = (f"INSERT INTO licenses ({','.join(fields)}) "
                       f"VALUES ({','.join('?'*len(fields))})")
                cur = conn.execute(sql, [rec[f] for f in fields])
                new_ids.append(cur.lastrowid)
        conn.commit()
    finally:
        conn.close()
    if mode == "overwrite":
        log_activity(request, "batch_renew", detail=f"Batch renewed (overwrite) {len(overwritten_ids)} record(s) in place — no history copies kept")
        return {"ok": True, "renewed": len(overwritten_ids), "new_ids": overwritten_ids, "mode": "overwrite"}
    log_activity(request, "batch_renew", detail=f"Batch renewed {len(new_ids)} record(s) from {len(source_ids)} selected")
    return {"ok": True, "renewed": len(new_ids), "new_ids": new_ids, "mode": "new"}


# ---------------------------------------------------------------- ANALYTICS
@router.get("/api/licenses/{lic_id}/payments")
def list_payments(lic_id: int):
    conn = get_conn()
    pays = conn.execute(
        "SELECT * FROM payments WHERE license_id = ? ORDER BY year", (lic_id,)).fetchall()
    conn.close()
    return [dict(p) for p in pays]

@router.post("/api/licenses/{lic_id}/payments")
def add_payment(lic_id: int, data: dict = Body(...)):
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM licenses WHERE id = ?", (lic_id,)).fetchone():
        conn.close(); raise HTTPException(404, "License not found")
    payload = clean_payload(conn, "payments", data)
    payload["license_id"] = lic_id
    fields = list(payload.keys())
    sql = (f"INSERT INTO payments ({','.join(fields)}) "
           f"VALUES ({','.join('?' * len(fields))})")
    cur = conn.execute(sql, [payload[f] for f in fields])
    conn.commit(); pid = cur.lastrowid; conn.close()
    return {"ok": True, "payment_id": pid}

@router.put("/api/payments/{pid}")
def update_payment(pid: int, data: dict = Body(...)):
    conn = get_conn()
    if not conn.execute("SELECT 1 FROM payments WHERE id = ?", (pid,)).fetchone():
        conn.close(); raise HTTPException(404, "Payment not found")
    payload = clean_payload(conn, "payments", data)
    payload.pop("license_id", None)  # don't allow re-parenting
    if not payload:
        conn.close(); raise HTTPException(400, "No valid fields supplied")
    sets = ", ".join(f"{f} = ?" for f in payload)
    conn.execute(f"UPDATE payments SET {sets} WHERE id = ?",
                 list(payload.values()) + [pid])
    conn.commit(); conn.close()
    return {"ok": True, "payment_id": pid}

@router.delete("/api/payments/{pid}")
def delete_payment(pid: int):
    conn = get_conn()
    cur = conn.execute("DELETE FROM payments WHERE id = ?", (pid,))
    conn.commit(); conn.close()
    if cur.rowcount == 0:
        raise HTTPException(404, "Payment not found")
    return {"ok": True, "deleted": pid}
