"""Second pass of the router extraction (see extract.py): wraps each raw
slice in an APIRouter, fixes imports, and writes the final app/routers/*.py.
One-off script, safe to delete after the restructuring is verified.
"""
import re

HEADERS = {
"auth.py": '''"""app/routers/auth.py — /api/login, /api/pin-login, /api/set-my-pin,
/api/clear-my-pin, /api/logout, /api/auth-status, /api/my-permissions,
/api/setup-admin. Moved verbatim from main.py (zero logic changes, still
raw sqlite3 via app.core.get_conn)."""
import secrets
from fastapi import APIRouter, HTTPException, Body, Request

from app.core import (
    get_conn, hash_pw, _new_token_entry, _effective_permissions,
    any_user_exists, _current_user_info, TOKENS, ALL_PERMISSIONS,
    LOGIN_ATTEMPTS, LOGIN_LOCKOUT_SECONDS, LOGIN_MAX_ATTEMPTS,
)

router = APIRouter(tags=["auth"])

''',
"settings.py": '''"""app/routers/settings.py — /api/settings, /api/backup-status,
/api/backup/run-now. Moved verbatim from main.py."""
import os
import json
import shutil
import datetime
from fastapi import APIRouter, HTTPException, Body, Request

from app.config import DB
from app.core import get_conn, role_for

router = APIRouter(tags=["settings"])

''',
"users.py": '''"""app/routers/users.py — /api/users*, /api/permissions-catalog,
/api/activity-log. Moved verbatim from main.py."""
import secrets
import json
from fastapi import APIRouter, HTTPException, Body, Request

from app.core import (
    get_conn, hash_pw, role_for, require_permission, log_activity,
    ALL_PERMISSIONS, PERMISSION_LABELS,
)
from app.routers.settings import require_super_admin

router = APIRouter(tags=["users"])

''',
"pages.py": '''"""app/routers/pages.py — "/" (existing index.html, unchanged) plus the
new HTMX/Jinja2 search page added in step 6 of MODERNIZATION_PLAN.md."""
import os
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import or_
from fastapi import Depends

from app.deps import get_db
from app.models.license import License

router = APIRouter(tags=["pages"])
templates = Jinja2Templates(directory="app/templates")

''',
"licenses.py": '''"""app/routers/licenses.py — /api/licenses*, history, location-check,
batch/renew, payments. Moved verbatim from main.py; still raw sqlite3
except for the handful of endpoints ported to SQLAlchemy in step 5 (see
bottom of this file / NOTES.md)."""
import math as _math
import datetime
from fastapi import APIRouter, HTTPException, Body, Query, Request

from app.config import DB
from app.core import get_conn, cols, clean_payload, role_for, require_permission, log_activity, _diff_summary

router = APIRouter(tags=["licenses"])

''',
"trash.py": '''"""app/routers/trash.py — /api/trash, /restore, /purge, /trash/empty,
/api/wipe-all. Moved verbatim from main.py."""
import os
from fastapi import APIRouter, HTTPException, Body, Request

from app.config import DB
from app.core import get_conn, role_for, require_permission, log_activity

router = APIRouter(tags=["trash"])

''',
"analytics.py": '''"""app/routers/analytics.py — /api/meta, /api/stats, /api/analytics*,
/api/or-batches*, /api/recent, /api/export. Moved verbatim from main.py."""
import io
import datetime
from fastapi import APIRouter, HTTPException, Body, Query, Request
from fastapi.responses import StreamingResponse

from app.config import DB
from app.core import get_conn, role_for, require_permission, log_activity

router = APIRouter(tags=["analytics"])

''',
"print.py": '''"""app/routers/print.py — /api/print/{id}, /api/print-word/{id}. Thin
wrappers calling app.legacy.print_engine* unchanged (Windows/COM only)."""
from fastapi import APIRouter, HTTPException, Request

from app.config import DB
from app.core import get_conn, role_for, require_permission, log_activity

router = APIRouter(tags=["print"])

''',
"import_.py": '''"""app/routers/import_.py — /api/import*, /api/import-flags*. Moved
verbatim from main.py."""
import re
import json
import datetime
from fastapi import APIRouter, HTTPException, Body, Query, Request

from app.config import DB
from app.core import get_conn, cols, clean_payload, role_for, require_permission, log_activity

router = APIRouter(tags=["import"])

''',
"scan.py": '''"""app/routers/scan.py — /api/scan*. Moved verbatim from main.py."""
import os
import json
import base64
import datetime
from fastapi import APIRouter, HTTPException, Body, Query, Request
from fastapi.responses import FileResponse

from app.config import DB
from app.core import get_conn, cols, clean_payload, role_for, require_permission, log_activity

router = APIRouter(tags=["scan"])

''',
}

import os as _os
ROUTER_DIR = "/tmp/ntc/app/routers"
for fname, header in HEADERS.items():
    raw_path = f"{ROUTER_DIR}/{fname}.raw"
    if not _os.path.exists(raw_path):
        print("MISSING", raw_path); continue
    text = open(raw_path, encoding="utf-8").read()
    text = re.sub(r'@app\.', '@router.', text)
    out = header + text
    with open(f"{ROUTER_DIR}/{fname}", "w", encoding="utf-8") as f:
        f.write(out)
    _os.remove(raw_path)
print("done")
