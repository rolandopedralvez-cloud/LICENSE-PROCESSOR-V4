"""baseline: existing schema as-is

Revision ID: 5c34a3fa9eaa
Revises:
Create Date: 2026-08-20 14:31:49.898085

This migration intentionally does nothing. It exists only as the Alembic
"revision 0" marker for a database that already has the full schema
(created by create_db.py + main.py's ensure_schema(), not by Alembic).

`alembic revision --autogenerate` initially produced a long list of
op.alter_column(...) calls changing TEXT() to String() and adding explicit
nullable=False to primary-key columns. Those are NOT real schema
differences — SQLite has no distinct TEXT/VARCHAR storage types (both get
"TEXT affinity"), and primary keys are implicitly NOT NULL already; the
autogenerate diff was comparing SQLAlchemy's Python-side type
representation against SQLite's own introspection, which is a known
false-positive category for this database backend, not an actual
migration. Applying that generated upgrade() as-is would also fail outright
on SQLite, since SQLite doesn't support ALTER COLUMN without Alembic's
--render-as-batch mode.

Verified column-by-column with `sqlalchemy.inspect(engine).get_columns()`
against every app/models/*.py model before generating this file (see
MODERNIZATION_PLAN.md section 3.2) — DB and models matched exactly with
zero missing/extra tables or columns. This file was then hand-emptied to
upgrade()/downgrade() no-ops, and `alembic stamp head` was used to mark an
already-fully-schemaed telco.db as being at this revision WITHOUT running
any SQL against it (stamp only writes to Alembic's own bookkeeping table,
alembic_version).

Everything from here forward is a REAL migration (see
MODERNIZATION_PLAN.md section 3.5) — do not add more no-op baseline-style
revisions.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5c34a3fa9eaa'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op — see module docstring."""
    pass


def downgrade() -> None:
    """No-op — see module docstring."""
    pass
