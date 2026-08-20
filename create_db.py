"""
create_db.py  —  NTC Region II Telco Database
Creates an empty SQLite database (telco.db) with two linked tables:
  licenses  : one row per RSL record
  payments  : one row per license per year (linked to licenses by license_id)
Run this once:  python create_db.py
"""

import sqlite3
import os

DB_FILE = "telco.db"

# Safety: don't silently overwrite an existing database
if os.path.exists(DB_FILE):
    print(f"'{DB_FILE}' already exists. Delete it first if you want a fresh one.")
    raise SystemExit

conn = sqlite3.connect(DB_FILE)
cur = conn.cursor()

# Enforce the license <-> payments link
cur.execute("PRAGMA foreign_keys = ON;")

# ---------- MAIN TABLE: licenses ----------
cur.execute("""
CREATE TABLE licenses (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Identity
    status            TEXT,
    license_no        TEXT,
    rsl_date          TEXT,
    licensee          TEXT,
    to_operate        TEXT,

    -- Location
    site_no           TEXT,
    site_name         TEXT,
    address           TEXT,
    brgy              TEXT,
    town              TEXT,
    province          TEXT,
    region            TEXT,
    zip_code          TEXT,
    psgc              TEXT,

    -- Coordinates
    elong_deg         TEXT,
    elong_min         TEXT,
    elong_sec         TEXT,
    nlat_deg          TEXT,
    nlat_min          TEXT,
    nlat_sec          TEXT,

    -- Radio / technical
    class_of_station  TEXT,
    nature_of_service TEXT,
    callsign          TEXT,
    hours             TEXT,
    points_of_comm    TEXT,
    freq1             TEXT,
    freq2             TEXT,
    freq3             TEXT,
    freq4             TEXT,
    pol               TEXT,
    bw_emission       TEXT,
    power             TEXT,
    capacity          TEXT,
    directive         TEXT,
    hag               TEXT,
    gain              TEXT,
    type              TEXT,

    -- Form references
    new_form_no       TEXT,
    old_form_no       TEXT,
    old_date          TEXT,

    -- Equipment
    tech              TEXT,
    config            TEXT,
    total             TEXT,
    make_model        TEXT,
    freq_range        TEXT,
    serial_no         TEXT,
    no_of_channels    TEXT,

    -- Base validity / OR
    validity_from     TEXT,
    validity_to       TEXT,
    or_no             TEXT,
    or_date           TEXT,
    or_amount         TEXT,
    dst               TEXT,
    signatory         TEXT,
    designation       TEXT,
    processor         TEXT,

    -- Misc
    case_number       TEXT,
    other_remarks     TEXT,
    other_reference   TEXT,
    license_status    TEXT,

    -- Bookkeeping (auto-managed)
    created_at        TEXT DEFAULT (datetime('now','localtime')),
    updated_at        TEXT DEFAULT (datetime('now','localtime'))
);
""")

# ---------- CHILD TABLE: payments ----------
cur.execute("""
CREATE TABLE payments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    license_id  INTEGER NOT NULL,
    year        INTEGER,
    or_no       TEXT,
    or_date     TEXT,
    or_amount   TEXT,
    suf_paid    TEXT,
    remarks     TEXT,
    FOREIGN KEY (license_id) REFERENCES licenses(id) ON DELETE CASCADE
);
""")

# ---------- Indexes for fast search ----------
cur.execute("CREATE INDEX idx_licenses_license_no ON licenses(license_no);")
cur.execute("CREATE INDEX idx_licenses_licensee   ON licenses(licensee);")
cur.execute("CREATE INDEX idx_licenses_province   ON licenses(province);")
cur.execute("CREATE INDEX idx_payments_license_id ON payments(license_id);")

conn.commit()

# ---------- Confirm ----------
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
tables = [r[0] for r in cur.fetchall()]
print("Database created:", DB_FILE)
print("Tables:", ", ".join(tables))
cur.execute("PRAGMA table_info(licenses);")
print("licenses columns:", len(cur.fetchall()))
cur.execute("PRAGMA table_info(payments);")
print("payments columns:", len(cur.fetchall()))

conn.close()
