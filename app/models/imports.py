"""
app/models/imports.py — SQLAlchemy models for `import_flags` and
`quarantine_scans`. Transcribed from ensure_schema() in main.py.
"""
from sqlalchemy import Column, Integer, String

from app.database import Base


class ImportFlag(Base):
    __tablename__ = "import_flags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(String, nullable=False)
    username = Column(String)
    status = Column(String, nullable=False)
    license_no = Column(String)
    licensee = Column(String)
    existing_id = Column(Integer)
    diff_json = Column(String)
    action_taken = Column(String)
    resolved = Column(Integer, nullable=False, default=0)
    resolved_by = Column(String)
    resolved_ts = Column(String)
    ignored = Column(Integer, nullable=False, default=0)
    ignored_by = Column(String)
    ignored_ts = Column(String)


class QuarantineScan(Base):
    __tablename__ = "quarantine_scans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(String, nullable=False)
    uploaded_by = Column(String)
    filename = Column(String)
    stored_path = Column(String)
    status = Column(String, nullable=False, default="pending")
    extracted_json = Column(String)
    corrected_json = Column(String)
    low_confidence = Column(String)
    extract_error = Column(String)
    license_id = Column(Integer)
    reviewed_by = Column(String)
    reviewed_ts = Column(String)
