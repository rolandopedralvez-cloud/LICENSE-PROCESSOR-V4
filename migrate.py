"""
migrate.py  —  Load TELCO_DATABASE_FINAL.xlsx into telco.db
Run once, AFTER create_db.py, with both files in the same folder:
    python migrate.py
"""
import sqlite3, os, datetime, openpyxl

DB_FILE    = "telco.db"
XLSX_FILE  = "TELCO_DATABASE_FINAL.xlsx"

# ---- cleanup maps (raw value is always preserved separately) ----
def clean_region(v):
    if v in (None, ""): return v
    return "Region II"

CLASS_MAP = {
    "FB (BWA)": "FB-BWA",
    "FB(BWA)":  "FB-BWA",
    "FB (WDN)": "FB-WDN",
}
def clean_class(v):
    if v in (None, ""): return v
    return CLASS_MAP.get(str(v).strip(), str(v).strip())

def cv(v):
    """Normalize a cell value for TEXT storage; dates -> ISO string."""
    if v is None: return None
    if isinstance(v, (datetime.datetime, datetime.date)):
        return v.strftime("%Y-%m-%d")
    return v

# Excel col (1-based) -> licenses field
COLMAP = {
    1:"status",2:"license_no",3:"rsl_date",4:"licensee",5:"to_operate",
    6:"site_no",7:"site_name",8:"address",9:"brgy",10:"town",11:"province",
    13:"zip_code",14:"psgc",
    15:"elong_deg",16:"elong_min",17:"elong_sec",18:"nlat_deg",19:"nlat_min",20:"nlat_sec",
    22:"nature_of_service",23:"callsign",24:"hours",25:"points_of_comm",
    26:"freq1",27:"freq2",28:"freq3",29:"freq4",30:"pol",31:"bw_emission",
    32:"power",33:"capacity",34:"directive",35:"hag",36:"gain",37:"type",
    38:"new_form_no",39:"old_form_no",40:"old_date",
    41:"tech",42:"config",43:"total",44:"make_model",45:"freq_range",46:"serial_no",
    47:"validity_from",48:"validity_to",
    49:"or_no",50:"or_date",51:"or_amount",52:"dst",53:"signatory",54:"designation",55:"processor",
    57:"case_number",58:"other_remarks",59:"other_reference",
    141:"license_status",142:"no_of_channels",
}

if not os.path.exists(DB_FILE):
    print(f"'{DB_FILE}' not found. Run create_db.py first."); raise SystemExit
if not os.path.exists(XLSX_FILE):
    print(f"'{XLSX_FILE}' not found. Put it in this folder."); raise SystemExit

conn = sqlite3.connect(DB_FILE)
cur = conn.cursor()
cur.execute("PRAGMA foreign_keys = ON;")

# Refuse to double-load
cur.execute("SELECT COUNT(*) FROM licenses;")
if cur.fetchone()[0] > 0:
    print("licenses table already has data. Aborting to avoid duplicates.")
    raise SystemExit

# Ensure raw-value columns exist (idempotent)
for col in ("region_raw", "class_of_station_raw"):
    try: cur.execute(f"ALTER TABLE licenses ADD COLUMN {col} TEXT;")
    except sqlite3.OperationalError: pass

wb = openpyxl.load_workbook(XLSX_FILE, data_only=True)
ws = wb.active
last = 1342

lic_count = 0
pay_count = 0
for r in range(2, last+1):
    if not (ws.cell(row=r,column=2).value or ws.cell(row=r,column=4).value):
        continue

    rec = {field: cv(ws.cell(row=r,column=c).value) for c,field in COLMAP.items()}

    # cleaned + raw
    raw_region = ws.cell(row=r,column=12).value
    raw_class  = ws.cell(row=r,column=21).value
    rec["region"] = clean_region(raw_region)
    rec["region_raw"] = raw_region
    rec["class_of_station"] = clean_class(raw_class)
    rec["class_of_station_raw"] = raw_class

    fields = list(rec.keys())
    placeholders = ",".join("?"*len(fields))
    cur.execute(f"INSERT INTO licenses ({','.join(fields)}) VALUES ({placeholders})",
                [rec[f] for f in fields])
    lic_id = cur.lastrowid
    lic_count += 1

    # 2025 payment row if any 2025 data present
    old_or = ws.cell(row=r,column=60).value   # OLD OR
    or2025 = ws.cell(row=r,column=61).value   # OR 2025 (date)
    ammt   = ws.cell(row=r,column=62).value   # AMMT
    suf25  = ws.cell(row=r,column=63).value   # SUF PAID (2025)
    rem25  = ws.cell(row=r,column=64).value
    if any(x not in (None,"") for x in (old_or, or2025, ammt, suf25, rem25)):
        cur.execute("""INSERT INTO payments (license_id,year,or_no,or_date,or_amount,suf_paid,remarks)
                       VALUES (?,?,?,?,?,?,?)""",
                    (lic_id, 2025, cv(old_or), cv(or2025), cv(ammt), cv(suf25), cv(rem25)))
        pay_count += 1

conn.commit()
print(f"Migrated {lic_count} licenses.")
print(f"Created  {pay_count} payment rows (year 2025).")

# sanity
cur.execute("SELECT COUNT(*) FROM licenses;"); print("licenses total:", cur.fetchone()[0])
cur.execute("SELECT DISTINCT region FROM licenses;"); print("distinct region ->", [x[0] for x in cur.fetchall()])
cur.execute("SELECT class_of_station, COUNT(*) FROM licenses GROUP BY class_of_station ORDER BY 2 DESC;")
print("class_of_station ->", cur.fetchall())
conn.close()
