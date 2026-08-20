"""
print_stage_word.py  —  Field mapping for the Word (mail-merge) RSL template.

Your RSL_Format_2025.docx already has real Word MERGEFIELD codes built in
(you set these up yourself). This module knows which database column feeds
each Word field name, and formats values the way the template expects
(dates as "Month DD, YYYY", not "YYYY-MM-DD").
"""

import sqlite3
import datetime
import re

# Word field name -> database column. None = leave blank (not on this form).
WORD_FIELD_MAP = {
    "Status": "status",
    "LicenseNo": "license_no",
    "RSLDate": "rsl_date",
    "Licensee": "licensee",
    "ToOperate": "to_operate",
    "SiteNo": "site_no",
    "SiteName": "site_name",
    "Addrs1": "address",
    "Brgy": "brgy",
    "Town": "town",
    "Province": "province",
    "Region": "region",
    "Philippine_Standard_Geographic_Code_PSG": "psgc",
    "ELongDeg": "elong_deg", "ELongMin": "elong_min", "ELongSec": "elong_sec",
    "NLatDeg": "nlat_deg", "NLatMin": "nlat_min", "NLatSec": "nlat_sec",
    "ClassOfStation": "class_of_station",
    "NatureOfService": "nature_of_service",
    "CallSign": "callsign",
    "Hours": "hours",
    "PointsOfCommunication": "points_of_comm",
    "Freq1": "freq1",          # Tx (MHz)
    "Freq3": "freq3",          # Rx (MHz)
    "BWEmission": "bw_emission",
    "Power": "power",
    "Directive": "directive",
    "HAG": "hag",
    "Gain": "gain",
    "Type": "type",
    "Pol": "pol",
    "Cap": "capacity",
    "OldFormNo": "old_form_no",
    "OldDate": "old_date",
    "Tech": "tech",
    "Config": "config",
    "MakeTypeModel": "make_model",
    "SerialNo": "serial_no",
    "FreqRange": "freq_range",
    "ValidityFrom": "validity_from",
    "ValidityTo": "validity_to",
    "ORNo": "or_no",
    "ORDate": "or_date",
    "ORAmount": "or_amount",
    "DST": "dst",
    "Signatory": "signatory",
    "Designation": "designation",
    "Processor": "processor",
}

DATE_FIELDS = {"RSLDate", "OldDate", "ValidityFrom", "ValidityTo", "ORDate"}
FREQ_FIELDS = {"Freq1", "Freq3"}
COORD_SYMBOLS = {
    "ELongDeg": "\u00b0", "NLatDeg": "\u00b0",   # °
    "ELongMin": "'",      "NLatMin": "'",         # '
    "ELongSec": '"',      "NLatSec": '"',         # " (proper seconds mark)
}


def _strip_freq_label(v):
    """
    freq1/freq3 sometimes start with their own "TX (MHz)"/"RX (MHz)" label
    baked into the value — but the template already has that as a static
    header above the box, so showing both looks doubled. This removes that
    leading label line, and also drops a trailing all-zero decimal remainder
    (".0000" etc.) since it never adds real information to a frequency value.
    Everything else in the value (repeats, line breaks) is left as stored.
    """
    if not v:
        return ""
    lines = str(v).splitlines()
    if lines and lines[0].strip().upper() in ("TX (MHZ)", "RX (MHZ)", "TX(MHZ)", "RX(MHZ)"):
        lines = lines[1:]
    cleaned = [re.sub(r'\.0+(?=\s*$)', '', ln) for ln in lines]
    return "\n".join(cleaned).strip("\n")


def _clean_freq(v):
    """
    freq1-4 often contain messy repeated text (label repeated, value repeated
    several times, trailing .0000). This just keeps the first real value —
    simple and handles every pattern we've seen.
    """
    if not v:
        return ""
    lines = [ln.strip() for ln in str(v).splitlines() if ln.strip()]
    lines = [ln for ln in lines if ln.upper() not in ("TX (MHZ)", "RX (MHZ)", "TX(MHZ)", "RX(MHZ)")]
    if not lines:
        return str(v).strip()
    first = lines[0]
    first = re.sub(r'\.0+(?=\s*$)', '', first)   # drop a meaningless trailing .0000
    return first


def _format_date(v):
    """'YYYY-MM-DD' -> 'Month DD, YYYY' to match the template's style."""
    if not v:
        return ""
    s = str(v)[:10]
    try:
        d = datetime.datetime.strptime(s, "%Y-%m-%d")
        return d.strftime("%B %d, %Y").replace(" 0", " ")
    except ValueError:
        return str(v)  # already formatted, or not a date we recognize


def fetch_record(db_path, lic_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM licenses WHERE id = ?", (lic_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def word_field_values(record):
    """Return {WordFieldName: display_value} ready to drop into the template."""
    out = {}
    for word_name, db_col in WORD_FIELD_MAP.items():
        v = record.get(db_col)
        if v is None:
            v = ""
        if word_name in DATE_FIELDS:
            v = _format_date(v)
        elif word_name in COORD_SYMBOLS:
            v = f"{v}{COORD_SYMBOLS[word_name]}" if v not in ("", None) else ""
        out[word_name] = str(v)
    return out
