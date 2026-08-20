"""
app/database.py — SQLAlchemy engine + session factory.

Points at the SAME telco.db file the existing raw-sqlite3 code in main.py
uses. This is intentional: during the incremental migration, both the old
sqlite3-based routes (still in main.py) and the new SQLAlchemy-based routes
(in app/routers/*) read/write the same physical database file. Nothing here
creates or alters tables — table creation/upgrades stay owned by
main.py's ensure_schema() until each table's migrations are fully moved
to Alembic (see MODERNIZATION_PLAN.md, section 3).
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DB_PATH = "telco.db"

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
