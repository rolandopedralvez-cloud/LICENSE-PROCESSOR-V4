"""
app/main.py — FastAPI application entrypoint.

Run:  uvicorn app.main:app --reload
Then open:  http://127.0.0.1:8000/docs

This replaces the old `uvicorn main:app` entrypoint. Update start.bat /
NTC.vbs / desktop.py to point at app.main:app (see NOTES.md).

Structure: app.core holds the shared helpers (auth/tokens, permissions,
activity log, ensure_schema — moved verbatim from main.py, zero logic
changes). app.routers/* holds the route handlers, split by feature area.
A handful of read-only routes have been ported to SQLAlchemy (app.routers
.meta, app.routers.licenses_ro, app.routers.pages) as the first step of the
incremental ORM migration described in MODERNIZATION_PLAN.md — everything
else still uses the original raw-sqlite3 helpers in app.core, on purpose,
and will be ported one router at a time later.
"""
import threading
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core import TOKENS, ensure_schema

# Ensure every model module is imported (and therefore every table known to
# SQLAlchemy's metadata) before anything else touches the database -- this
# matters for Alembic autogenerate/inspect, not for the raw-sqlite3 routes.
import app.models  # noqa: F401

from app.routers import (
    auth, users, meta, licenses_ro, licenses, analytics, import_, scan,
    print as print_router, trash, settings, pages,
)

app = FastAPI(title="NTC R02 Telco Database", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# Schema creation/upgrade still owned by ensure_schema() (raw sqlite3) until
# each table's migrations are fully moved to Alembic — see
# MODERNIZATION_PLAN.md section 3.5. ensure_schema() already ran once at
# import time inside app/core.py (matching main.py's original behavior of
# calling it at module load), so this is a no-op safety call.
ensure_schema()


# ---------------------------------------------------------------- auth guard
# Same behavior as main.py: any /api/* route not explicitly whitelisted
# requires a valid Bearer token. This applies to every router mounted below,
# including the new SQLAlchemy-based ones (app.routers.meta,
# app.routers.licenses_ro) — they don't reimplement auth themselves because
# this middleware already covers them.
_OPEN_PATHS = {"/api/login", "/api/pin-login", "/api/logout", "/api/auth-status", "/api/setup-admin"}


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api") and path not in _OPEN_PATHS:
        token = request.headers.get("authorization", "").replace("Bearer ", "").strip()
        if token not in TOKENS:
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return await call_next(request)


# ---------------------------------------------------------------- routers
# Order matters only in that FastAPI resolves the FIRST matching route.
# meta/licenses_ro (SQLAlchemy) are included before licenses (raw sqlite3)
# so their versions of /api/meta, /api/stats, /api/licenses{,/{id}},
# /api/licenses/{id}/history win; those exact paths have been removed from
# the later routers' source to avoid a dead second implementation
# (see the NOTE comments left in app/routers/licenses.py and
# app/routers/analytics.py).
app.include_router(meta.router)
app.include_router(licenses_ro.router)
app.include_router(pages.router)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(licenses.router)
app.include_router(analytics.router)
app.include_router(import_.router)
app.include_router(scan.router)
app.include_router(print_router.router)
app.include_router(trash.router)
app.include_router(settings.router)


# ---------------------------------------------------------------- background sweep + shutdown
FLAG_SWEEP_INTERVAL_SECONDS = 30 * 60  # how often the automatic duplicate-license sweep re-runs


def _flag_sweep_loop():
    while True:
        time.sleep(FLAG_SWEEP_INTERVAL_SECONDS)
        try:
            import_._sweep_duplicate_licenses()
        except Exception:
            pass  # a failed background sweep should never take the app down


@app.on_event("startup")
def _start_flag_sweep():
    try:
        import_._sweep_duplicate_licenses()
    except Exception:
        pass
    t = threading.Thread(target=_flag_sweep_loop, daemon=True)
    t.start()


@app.on_event("shutdown")
def _close_printer():
    try:
        from app.legacy import print_engine
        print_engine.shutdown()
    except Exception:
        pass
    try:
        from app.legacy import print_engine_word
        print_engine_word.shutdown()
    except Exception:
        pass
