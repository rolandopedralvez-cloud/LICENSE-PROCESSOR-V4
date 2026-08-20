"""
Import every model module here so that app.database.Base.metadata is fully
populated no matter which single module triggers the import (Alembic's
env.py relies on this — see alembic/env.py).
"""
from app.models.license import License, Payment       # noqa: F401
from app.models.user import User, ActivityLog, SchemaMeta  # noqa: F401
from app.models.imports import ImportFlag, QuarantineScan  # noqa: F401
