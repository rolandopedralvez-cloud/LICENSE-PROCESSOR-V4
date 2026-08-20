# NTC Licensing App — Modernization Plan
(FastAPI + raw sqlite3 + single index.html → FastAPI/routers + SQLAlchemy/Alembic + Jinja2/HTMX/Tailwind)

Based on a read of the actual repo (`main.py` ~2,700 lines / 76 routes, `main_updated.py` a divergent 78KB copy, `index.html` 242KB single-page vanilla-JS UI, plus `create_db.py`, `migrate.py`, `print_engine*.py`, `print_rsl*.py`, `print_stage*.py`, `fix_*.py`, `desktop.py`, `NTC.vbs`, `start.bat`).

---

## 0. What's actually risky here (read this first)

1. **`main_updated.py` is an undeclared fork.** It's 78KB, not imported anywhere, not referenced in `start.bat`/`NTC.vbs`/README. Before touching anything, `diff` it against `main.py` and find out if it's newer, older, or abandoned. If nobody can say confidently which one is "live," that's the actual #1 risk in this migration — you could refactor the wrong file for days. Resolve this in step 1, before any SQLAlchemy work.
2. **Schema is evolved entirely through `ensure_schema()`'s hand-written `ALTER TABLE ... IF NOT EXISTS`-style checks, run on every startup.** This is effectively a hand-rolled migration system already living in your code (permissions JSON backfill, role renames, etc.). Alembic needs to become the *only* source of schema change going forward, or you'll get drift between what Alembic thinks the schema is and what `ensure_schema()` silently does at boot. The migration plan below retires `ensure_schema()` piece by piece.
3. **Text-typed columns storing dates/numbers.** Every column in `licenses` is `TEXT`, including dates (`rsl_date`, `validity_from`, `or_date`) and numeric-ish fields (`or_amount`). SQLAlchemy models should map these as `String` initially too — do **not** "fix" the types as part of the ORM migration. Coercing `TEXT` → `Date`/`Numeric` at the same time as introducing SQLAlchemy conflates two risky changes; do type cleanup later, as its own reviewed step, once you have Alembic + tests in place.
4. **In-memory session tokens (`TOKENS = {}`)** reset on every restart/reload. That's fine today but will bite you the moment you run under `uvicorn --reload` in dev or move to multi-worker — worth a one-line callout in your issue tracker, not urgent for this migration.
5. **No test coverage found.** Before refactoring `/api/licenses`, `/api/import`, `/api/batch/renew`, `/api/print*` — the highest-traffic and highest-complexity endpoints — write characterization tests (call the existing endpoints against a copy of real `telco.db`, snapshot the JSON responses) so you have a regression net. This is more important than the ORM switch itself for a live app.
6. **Windows + pywin32 printing (`print_engine_word.py`, `print_rsl.py`, etc.) is COM automation against a running Excel/Word.** It cannot run in CI, in Docker, or on your dev machine if that's not Windows. Leave these files untouched and unimported by the new router structure except where explicitly called — don't let them get swept into "let's use Jinja2 for everything."

---

## 1. Target project structure

Keep this incremental — you are reorganizing `main.py`, not rewriting it. Move code, don't rewrite logic, in this pass.

```
ntc-app/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI() instance, CORS, mount routers, startup event
│   ├── deps.py                 # get_db() session dependency, get_current_user(), require_role()
│   ├── config.py                # DB path, token timeouts, paths — replaces scattered constants
│   ├── database.py              # SQLAlchemy engine + SessionLocal, Base
│   ├── models/
│   │   ├── __init__.py
│   │   ├── license.py            # License, Payment ORM models
│   │   ├── user.py                # User, ActivityLog
│   │   └── imports.py             # ImportFlag, ScanQueue (whatever backs /api/scan/*)
│   ├── schemas/                   # Pydantic request/response models (split out of main.py's Body(...) inline dicts)
│   │   ├── license.py
│   │   ├── user.py
│   │   └── auth.py
│   ├── routers/
│   │   ├── auth.py                # /api/login, /api/pin-login, /api/logout, /api/auth-status, /api/setup-admin
│   │   ├── users.py               # /api/users*, /api/permissions-catalog
│   │   ├── licenses.py            # /api/licenses*, /api/licenses/{id}/history, /api/licenses/{id}/payments
│   │   ├── analytics.py           # /api/stats, /api/analytics*, /api/or-batches*
│   │    import.py                  # /api/import*, /api/import-flags*
│   │   ├── scan.py                # /api/scan*
│   │   ├── print.py               # /api/print/{id}, /api/print-word/{id} — thin wrappers calling print_engine*.py unchanged
│   │   ├── trash.py               # /api/trash, /restore, /purge, /wipe-all
│   │   ├── settings.py            # /api/settings, /api/backup*
│   │   └── pages.py                # "/" and any future Jinja2/HTMX page routes
│   ├── templates/                 # Jinja2 — NEW, grows alongside index.html rather than replacing it day 1
│   │   ├── base.html               # Tailwind CDN, HTMX CDN, shared layout
│   │   ├── licenses/
│   │   │   ├── search.html          # full page shell
│   │   │   └── _results.html        # HTMX partial returned by the search endpoint
│   │   └── partials/
│   ├── static/                     # if/when you split JS out of index.html
│   ├── services/                   # business logic pulled out of routers: import matching, permission checks, activity logging
│   │   ├── activity.py
│   │   └── permissions.py
│   └── legacy/                     # print_engine.py, print_rsl.py, print_stage.py + _word variants, fix_*.py, migrate.py
│       └── (moved as-is, imports updated, zero logic changes)
├── alembic/
│   ├── env.py
│   └── versions/
├── alembic.ini
├── index.html                     # left in place at repo root, served as-is until pages migrate to templates/
├── telco.db
├── requirements.txt
├── start.bat
├── NTC.vbs
└── desktop.py
```

Notes on the mapping to what exists today:
- `print_engine.py`, `print_engine_word.py`, `print_rsl.py`, `print_rsl_word.py`, `print_stage.py`, `print_stage_word.py` move into `app/legacy/` unmodified — they're Windows/COM-only and orthogonal to this migration. `app/routers/print.py` just imports and calls them.
- `fix_license_status.py`, `fix_province.py` are one-off scripts — leave at repo root or move to a `scripts/` folder, not part of the app package.
- `create_db.py` becomes redundant once Alembic owns schema creation (step 3) — keep it around for one release as a documented fallback, then delete.
- `desktop.py` / `NTC.vbs` / `start.bat` only need a one-line change: they currently do (probably) `uvicorn main:app`; update to `uvicorn app.main:app`.

---

## 2. Packages to add

```
# requirements.txt additions — pin versions when you actually install, these are current-as-of-2025 majors
sqlalchemy>=2.0
alembic>=1.13
jinja2>=3.1
python-multipart          # FastAPI needs this for form/file uploads (you already have file-upload endpoints for /api/scan/upload and /api/import)
```

HTMX and Tailwind: use CDN `<script>`/`<link>` tags in `templates/base.html` — no npm/node build step needed, matches your "no build step" constraint and your current index.html approach of not having a bundler.

```html
<script src="https://unpkg.com/htmx.org@1.9.12"></script>
<script src="https://cdn.tailwindcss.com"></script>
```

Your existing `fastapi`, `uvicorn`, `openpyxl`, `pywin32`, `pywebview` stay as-is.

---

## 3. Step-by-step SQLAlchemy + Alembic migration (no data loss)

The core trick for an app already in production with a populated `telco.db`: **you do not let Alembic create the schema.** You point Alembic at the *existing* database, tell it "this is already at revision X" via `stamp`, and every migration from then on is additive (`ALTER TABLE ADD COLUMN`, matching what `ensure_schema()` already does by hand today).

### Step 3.1 — Define ORM models that match the CURRENT schema exactly
Read `create_db.py`'s `CREATE TABLE` statements and `ensure_schema()`'s added columns and transcribe them 1:1 — same column names, same nullability, `TEXT` fields as `String` (not `Date`/`Numeric`, per the risk note above).

```python
# app/models/license.py
from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base

class License(Base):
    __tablename__ = "licenses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    status = Column(String)
    license_no = Column(String)
    rsl_date = Column(String)          # TEXT in DB — do not coerce to Date yet
    licensee = Column(String)
    to_operate = Column(String)
    site_no = Column(String)
    site_name = Column(String)
    address = Column(String)
    brgy = Column(String)
    town = Column(String)
    province = Column(String)
    region = Column(String)
    region_raw = Column(String)
    zip_code = Column(String)
    psgc = Column(String)
    # ... transcribe every remaining column from create_db.py, same order, same TEXT->String mapping
    class_of_station = Column(String)
    class_of_station_raw = Column(String)
    # bookkeeping / soft-delete / import tracking added later by ensure_schema()
    renewed_from = Column(Integer)
    deleted_at = Column(String)
    import_batch = Column(String)
    created_at = Column(String)
    updated_at = Column(String)

    payments = relationship("Payment", back_populates="license", cascade="all, delete-orphan")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    license_id = Column(Integer, ForeignKey("licenses.id", ondelete="CASCADE"), nullable=False)
    year = Column(Integer)
    or_no = Column(String)
    or_date = Column(String)
    or_amount = Column(String)
    suf_paid = Column(String)
    remarks = Column(String)

    license = relationship("License", back_populates="payments")
```

Do the same for `User`, `ActivityLog`, `ImportFlag`, `SchemaMeta`, and whatever backs `/api/scan/*` (grep `main.py` around line 2394 for the actual `CREATE TABLE` to transcribe — it's not shown in `ensure_schema()`'s excerpt above, check further down that function).

```python
# app/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DB_PATH = "telco.db"   # keep using the same file — this is the "no data loss" part
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
```

### Step 3.2 — Verify the models match reality before Alembic ever runs
```bash
python -c "
from sqlalchemy import inspect
from app.database import engine
insp = inspect(engine)
print(insp.get_columns('licenses'))
"
```
Diff this output column-by-column against your ORM model. This is the single most important check in the whole plan — a mismatch here means Alembic's autogenerate will try to "fix" your live table on the first migration.

### Step 3.3 — Initialize Alembic and point it at the real DB
```bash
alembic init alembic
```
Edit `alembic.ini`:
```ini
sqlalchemy.url = sqlite:///telco.db
```
Edit `alembic/env.py` to import your models' metadata:
```python
from app.database import Base
from app.models import license, user, imports  # ensure all model modules are imported so Base.metadata is complete
target_metadata = Base.metadata
```

### Step 3.4 — Stamp the existing database as the baseline (this is the no-data-loss step)
```bash
# Generate a migration but do NOT run it — this captures your CURRENT schema as revision "baseline"
alembic revision --autogenerate -m "baseline: existing schema as-is"
```
Open the generated file in `alembic/versions/`. Because your models match the live DB exactly (step 3.2), this migration's `upgrade()` should be empty or near-empty. If autogenerate proposes `CREATE TABLE` or `DROP COLUMN` statements, **stop** — that means a model/DB mismatch, go back to 3.2. Once the generated migration is confirmed to be a no-op (or you've manually emptied it), mark the live DB as already being at that revision without running it:
```bash
alembic stamp head
```
`telco.db` is untouched by this — `stamp` only writes a row into Alembic's bookkeeping table (`alembic_version`), it does not touch your `licenses`/`payments` data.

### Step 3.5 — From here on, every schema change becomes a real Alembic migration
Take the pending, not-yet-applied changes currently living inside `ensure_schema()` (e.g., anything added since the last person ran the app) and convert them to real migrations:
```bash
alembic revision --autogenerate -m "add import_batch tracking to licenses"
alembic upgrade head
```
Then delete that specific `ALTER TABLE` line from `ensure_schema()` — it's now Alembic's job. Do this one column/table at a time, not all at once, so each step is independently revertible.

### Step 3.6 — Rewrite routers to use SQLAlchemy sessions instead of raw `sqlite3.connect`
```python
# app/deps.py
from app.database import SessionLocal

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```
```python
# app/routers/licenses.py — example of ONE endpoint ported, not all 76 at once
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.deps import get_db
from app.models.license import License

router = APIRouter(prefix="/api/licenses", tags=["licenses"])

@router.get("/{lic_id}")
def get_license(lic_id: int, db: Session = Depends(get_db)):
    lic = db.get(License, lic_id)
    if not lic or lic.deleted_at:
        raise HTTPException(404, "License not found")
    return lic  # add a Pydantic response_model once schemas/license.py exists
```
Port endpoints **one router file at a time**, run the app, click through that feature in the UI, commit, move to the next router. `/api/licenses` (search/list, the highest-traffic endpoint) last, since it likely has the most complex dynamic `WHERE` building — check `main.py` line ~928 before porting it, as dynamic filter-building is the part most likely to need `sqlalchemy.and_`/`or_` composition rather than a straight 1:1 port.

---

## 4. Working example: Jinja2 + Tailwind + HTMX search box

```python
# app/routers/pages.py
from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.deps import get_db
from app.models.license import License

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/search-ui")
def search_page(request: Request):
    return templates.TemplateResponse("licenses/search.html", {"request": request, "results": []})

@router.get("/search-ui/results")
def search_results(request: Request, q: str = "", db: Session = Depends(get_db)):
    query = db.query(License).filter(License.deleted_at.is_(None))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(License.licensee.ilike(like), License.license_no.ilike(like)))
    results = query.limit(50).all()
    return templates.TemplateResponse("licenses/_results.html", {"request": request, "results": results})
```

```html
{# app/templates/base.html #}
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{% block title %}NTC Licensing{% endblock %}</title>
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50 text-gray-900">
  <main class="max-w-5xl mx-auto p-6">
    {% block content %}{% endblock %}
  </main>
</body>
</html>
```

```html
{# app/templates/licenses/search.html #}
{% extends "base.html" %}
{% block content %}
<h1 class="text-2xl font-semibold mb-4">Search Licenses</h1>

<input
  type="search"
  name="q"
  placeholder="Licensee or license no..."
  class="w-full border border-gray-300 rounded-lg px-3 py-2 mb-4 focus:outline-none focus:ring-2 focus:ring-blue-500"
  hx-get="/search-ui/results"
  hx-trigger="keyup changed delay:300ms, search"
  hx-target="#results"
  hx-indicator="#spinner"
>
<span id="spinner" class="htmx-indicator text-sm text-gray-400">Searching…</span>

<div id="results">
  {% include "licenses/_results.html" %}
</div>
{% endblock %}
```

```html
{# app/templates/licenses/_results.html — the HTMX-swapped partial #}
<table class="w-full text-sm border-collapse">
  <thead>
    <tr class="text-left border-b border-gray-200">
      <th class="py-2">License No.</th>
      <th class="py-2">Licensee</th>
      <th class="py-2">Status</th>
    </tr>
  </thead>
  <tbody>
    {% for lic in results %}
    <tr class="border-b border-gray-100 hover:bg-gray-100">
      <td class="py-2">{{ lic.license_no }}</td>
      <td class="py-2">{{ lic.licensee }}</td>
      <td class="py-2">{{ lic.status }}</td>
    </tr>
    {% else %}
    <tr><td colspan="3" class="py-4 text-gray-400">No results.</td></tr>
    {% endfor %}
  </tbody>
</table>
```

Typing in the box fires a debounced `GET /search-ui/results?q=...` via HTMX, which returns just the `<table>` HTML fragment and swaps it into `#results` — no full page reload, no hand-written `fetch()`/`innerHTML` JS like the current `index.html` presumably does.

Register the router in `app/main.py`:
```python
from fastapi import FastAPI
from app.routers import pages, licenses, auth  # etc.

app = FastAPI(title="NTC R02 Telco Database", version="2.0")
app.include_router(pages.router)
app.include_router(licenses.router)
app.include_router(auth.router)
# existing index.html can still be served at "/" during the transition
```

---

## 5. Suggested sequencing (safe order of operations)

1. **Resolve `main_updated.py`.** Diff it, decide keep-or-delete, document the decision in the README. Do not proceed until there's one canonical backend file.
2. **Snapshot `telco.db`** (`cp telco.db telco.db.pre-migration.bak`) and write a handful of characterization tests against the current `main.py` for `/api/licenses`, `/api/licenses/{id}`, `/api/import`, `/api/batch/renew`, `/api/print*` (mock the COM calls or skip on non-Windows).
3. **Extract routers with zero logic changes** — literally cut-paste each `@app.get/post/...` block into the matching `app/routers/*.py` file, still using raw `sqlite3` underneath. This alone is a huge maintainability win and is low-risk because you're not touching queries.
4. **Introduce SQLAlchemy models + Alembic baseline** (section 3.1–3.5) alongside the still-raw-sqlite3 routers — they can coexist; Alembic doesn't care that routers aren't using the ORM yet.
5. **Port routers to SQLAlchemy one at a time**, starting with the simplest read-only ones (`/api/meta`, `/api/stats`) to prove the pattern, ending with `/api/licenses` search and `/api/import` (most complex).
6. **Add the first HTMX/Jinja2 page as a new, additional route** (e.g., `/search-ui`) that lives *next to* the existing `index.html`-served `/`. Don't replace `/` until the new UI has full feature parity for that page. This lets you dogfood the new stack without a flag day.
7. **Only after 1–6 are stable**, consider the TEXT→Date/Numeric column type cleanup, as its own separate, reviewed migration.

Test after every single step by running the app and clicking through the corresponding feature — this is a live single-user LAN tool, so a manual smoke pass after each step is proportionate; you don't need a full CI pipeline to do this migration safely.
</content>
