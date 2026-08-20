"""
app/models/user.py — SQLAlchemy models for `users` and `activity_log`.
Transcribed from ensure_schema() in main.py.
"""
from sqlalchemy import Column, Integer, String, LargeBinary

from app.database import Base


class User(Base):
    __tablename__ = "users"

    username = Column(String, primary_key=True)
    salt = Column(LargeBinary, nullable=False)
    pwhash = Column(LargeBinary, nullable=False)
    role = Column(String, default="admin")
    pin_salt = Column(LargeBinary)
    pin_hash = Column(LargeBinary)
    # JSON-encoded array of strings — kept as-is (not normalized into a
    # separate permissions table) to match the live schema exactly.
    permissions = Column(String)


class ActivityLog(Base):
    __tablename__ = "activity_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(String, nullable=False)
    username = Column(String)
    action = Column(String, nullable=False)
    license_id = Column(Integer)
    license_no = Column(String)
    detail = Column(String)


class SchemaMeta(Base):
    __tablename__ = "schema_meta"

    key = Column(String, primary_key=True)
    value = Column(String)
