"""
app/deps.py — FastAPI dependency helpers for the new SQLAlchemy-based
routers (app/routers/*).

Deliberately small right now: only get_db() is needed by the routers ported
so far (app/routers/meta.py, app/routers/licenses_ro.py), because those
endpoints match their main.py originals, which do not require auth either
(read the endpoints in main.py — /api/meta, /api/stats,
/api/licenses/{id}/history, /api/licenses, /api/licenses/{id} — none of
them call require_permission or role_for).

When a write-capable or auth-gated endpoint gets ported next, add a
get_current_user()/require_permission() dependency here that reads from the
SAME in-memory TOKENS dict main.py uses, so a session started against the
old routes stays valid against the new ones. Do not build a second,
parallel auth system.
"""
from fastapi import HTTPException, Request

from app.database import SessionLocal
from app.core import _current_user_info


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_login(request: Request):
    """
    Auth dependency for the new /app/* page + data routes.

    Reuses app.core's EXACT token lookup (_current_user_info, backed by the
    same TOKENS dict main.py already populates on /api/login) rather than a
    second auth system — a token issued by the classic UI's login works
    here too, and vice versa.

    Why this can't just be "handled by the middleware": the global
    auth_guard middleware in app/main.py only protects paths starting with
    "/api". The /app/* routes are page/HTML-fragment routes, not /api/*, so
    they need to check auth explicitly. (Their write operations still go
    straight to the existing /api/licenses* endpoints from client-side JS,
    which ARE covered by the middleware — this dependency is only for the
    /app/* routes that themselves read/render license data server-side.)
    """
    info = _current_user_info(request)
    if not info:
        raise HTTPException(401, "Not authenticated")
    return info
