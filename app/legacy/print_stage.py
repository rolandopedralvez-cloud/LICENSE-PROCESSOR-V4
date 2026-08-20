"""
print_stage.py  —  Field mapping for the internal STAGING sheet.

Your PRINT_ready.xlsx now has a STAGING sheet (same 59-column structure as
T_DB_2025). FRONT reads row 2 of STAGING. This module knows which database
field goes in which staging column, and prepares values (dates as real dates)
for the print script to write via Excel.
"""

import sqlite3
import datetime

# STAGING column order (1-based) -> licenses field in telco.db. None = blank.
STAGING_FIELDS = [
    "status","license_no","rsl_date","licensee","to_operate","site_no",
    "site_name","address","brgy","town","province","region","zip_code","psgc",
    "elong_deg","elong_min","elong_sec","nlat_deg","nlat_min","nlat_sec",
    "class_of_station","nature_of_service","callsign","hours","points_of_comm",
    "freq1","freq2","freq3","freq4","pol","bw_emission","power","capacity",
    "directive","hag","gain","type","new_form_no","old_form_no","old_date",
    "tech","config","total","make_model","freq_range","serial_no",
    "validity_from","validity_to","or_no","or_date","or_amount","dst",
    "signatory","designation","processor", None, "case_number",
    "other_remarks","other_reference",
]

DATE_FIELDS = {"rsl_date", "old_date", "validity_from", "validity_to", "or_date"}
STAGING_SHEET = "STAGING"
STAGING_ROW = 2   # FRONT reads this row

STAGING_HEADERS = [
    "Status","LicenseNo","RSLDate","Licensee","ToOperate","SiteNo.","SiteName",
    "Addrs1","Brgy.","Town","Province","Region","ZipCode",
    "Philippine Standard Geographic Code (PSGC)","ELongDeg","ELongMin","ELongSec",
    "NLatDeg","NLatMin","NLatSec","ClassOfStation","NatureOfService","CallSign",
    "Hours","PointsOfCommunication","Freq1","Freq2","Freq3","Freq4","Pol",
    "BW&Emission","Power","Capacity","Directive","HAG","Gain","Type","NewFormNo",
    "OldFormNo","OldDate","Tech","Config","TOTAL","MakeTypeModel","FreqRange",
    "SerialNo","ValidityFrom","ValidityTo","ORNo","ORDate","ORAmount","DST",
    "Signatory","Designation","Processor","SUF PAID","CASE NUMBER",
    "OTHER REMARKS","REFERENCE",
]


def _to_date(v):
    """'YYYY-MM-DD' -> real datetime; anything else unchanged."""
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v
    if isinstance(v, str) and len(v) >= 10 and v[4] == "-" and v[7] == "-":
        try:
            return datetime.datetime(int(v[0:4]), int(v[5:7]), int(v[8:10]))
        except ValueError:
            return v
    return v


def fetch_record(db_path, lic_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM licenses WHERE id = ?", (lic_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def staging_cells(record):
    """Return [(column_index, value), ...] for STAGING row 2. Dates -> real dates."""
    cells = []
    for col, field in enumerate(STAGING_FIELDS, start=1):
        if field is None:
            continue
        v = record.get(field)
        if v in (None, ""):
            continue
        if field in DATE_FIELDS:
            v = _to_date(v)
        cells.append((col, v))
    return cells
