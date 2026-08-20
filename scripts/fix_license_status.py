"""
fix_license_status.py  —  Fill in blank license_status from the Status column.

Your database has two status columns (a leftover from the original Excel
layout): "status" and "license_status". The search list's Type badge reads
license_status specifically. If it's blank while "status" has a value
(e.g. after an Import), this copies it across.

SAFE: backs up telco.db first. Only fills license_status where it's blank
AND status has a real value — never overwrites an existing license_status.

Run:  python fix_license_status.py
"""

import sqlite3
import shutil
import os
import datetime

DB = "telco.db"

if not os.path.exists(DB):
    print(f"'{DB}' not found in this folder."); raise SystemExit

ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
backup = f"telco_backup_{ts}.db"
shutil.copy(DB, backup)
print(f"Backup saved: {backup}")

conn = sqlite3.connect(DB)
cur = conn.execute(
    "UPDATE licenses SET license_status = status "
    "WHERE (license_status IS NULL OR license_status = '') "
    "AND status IS NOT NULL AND status <> ''"
)
conn.commit()
n = cur.rowcount
conn.close()

print(f"Filled license_status on {n} record(s).")
print("Done. If anything looks wrong, restore from the backup file above.")
