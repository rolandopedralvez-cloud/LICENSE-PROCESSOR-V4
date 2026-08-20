"""
app/models/license.py — SQLAlchemy models for `licenses` and `payments`.

Column list transcribed 1:1 from create_db.py's CREATE TABLE statements,
plus the columns added later by migrate.py (region_raw, class_of_station_raw)
and by main.py's ensure_schema() (renewed_from, deleted_at, import_batch).

IMPORTANT: every column here is TEXT in the real database, including dates
(rsl_date, validity_from/to, or_date...) and numeric-looking fields
(or_amount). They are intentionally mapped as String, not Date/Numeric —
see MODERNIZATION_PLAN.md risk note #3. Do not "fix" these types here;
that is a separate, later migration.
"""
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


class License(Base):
    __tablename__ = "licenses"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identity
    status = Column(String)
    license_no = Column(String)
    rsl_date = Column(String)
    licensee = Column(String)
    to_operate = Column(String)

    # Location
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

    # Coordinates
    elong_deg = Column(String)
    elong_min = Column(String)
    elong_sec = Column(String)
    nlat_deg = Column(String)
    nlat_min = Column(String)
    nlat_sec = Column(String)

    # Radio / technical
    class_of_station = Column(String)
    class_of_station_raw = Column(String)
    nature_of_service = Column(String)
    callsign = Column(String)
    hours = Column(String)
    points_of_comm = Column(String)
    freq1 = Column(String)
    freq2 = Column(String)
    freq3 = Column(String)
    freq4 = Column(String)
    pol = Column(String)
    bw_emission = Column(String)
    power = Column(String)
    capacity = Column(String)
    directive = Column(String)
    hag = Column(String)
    gain = Column(String)
    type = Column(String)

    # Form references
    new_form_no = Column(String)
    old_form_no = Column(String)
    old_date = Column(String)

    # Equipment
    tech = Column(String)
    config = Column(String)
    total = Column(String)
    make_model = Column(String)
    freq_range = Column(String)
    serial_no = Column(String)
    no_of_channels = Column(String)

    # Base validity / OR
    validity_from = Column(String)
    validity_to = Column(String)
    or_no = Column(String)
    or_date = Column(String)
    or_amount = Column(String)
    dst = Column(String)
    signatory = Column(String)
    designation = Column(String)
    processor = Column(String)

    # Misc
    case_number = Column(String)
    other_remarks = Column(String)
    other_reference = Column(String)
    license_status = Column(String)

    # Added by ensure_schema() after initial release
    renewed_from = Column(Integer)
    deleted_at = Column(String)
    import_batch = Column(String)

    # Bookkeeping
    created_at = Column(String)
    updated_at = Column(String)

    payments = relationship(
        "Payment", back_populates="license", cascade="all, delete-orphan"
    )


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
