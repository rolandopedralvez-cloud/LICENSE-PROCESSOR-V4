"""
fix_province.py  —  Safely correct Province (and a Town/Barangay mix-up) in telco.db.

SAFE BY DESIGN:
  - Makes a timestamped backup of telco.db BEFORE changing anything.
  - Only fills in Province where it is blank AND the Town is confidently known
    (matched against the official Region II municipality list).
  - Only touches the ~42 records where the Barangay field literally contains
    a real town name and Town itself is blank (a data-entry mix-up) — moves
    that value into Town, and leaves Barangay blank rather than guessing.
  - NEVER invents Site No., Address, or Barangay values. Those need the
    physical case file, so this script leaves them alone and instead prints
    a "needs review" list of which records are missing them.

Run:  python fix_province.py
"""

import sqlite3
import shutil
import os
import datetime

DB = "telco.db"

# Official Region II municipalities/cities per province
MUNICIPALITIES = {
    "Batanes": ["Basco","Itbayat","Ivana","Mahatao","Sabtang","Uyugan"],
    "Cagayan": ["Abulug","Alcala","Allacapan","Amulung","Aparri","Baggao","Ballesteros",
        "Buguey","Calayan","Camalaniugan","Claveria","Enrile","Gattaran","Gonzaga","Iguig",
        "Lal-lo","Lasam","Pamplona","Peñablanca","Piat","Rizal","Sanchez Mira","Sta. Ana",
        "Sta. Praxedes","Sta. Teresita","Sto. Niño","Solana","Tuao","Tuguegarao City"],
    "Isabela": ["Alicia","Angadanan","Aurora","Benito Soliven","Burgos","Cabagan","Cabatuan",
        "Cauayan City","Cordon","Delfin Albano","Dinapigue","Divilacan","Echague","Gamu",
        "Ilagan City","Jones","Luna","Maconacon","Mallig","Naguilian","Palanan","Quezon",
        "Quirino","Ramon","Reina Mercedes","Roxas","San Agustin","San Guillermo","San Isidro",
        "San Manuel","San Mariano","San Mateo","San Pablo","Santiago City","Sta. Maria",
        "Sto. Tomas","Tumauini"],
    "Nueva Vizcaya": ["Alfonso Castañeda","Ambaguio","Aritao","Bagabag","Bambang","Bayombong",
        "Diadi","Dupax Del Norte","Dupax Del Sur","Kasibu","Kayapa","Quezon","Sta. Fe",
        "Solano","Villaverde"],
    "Quirino": ["Aglipay","Cabarroguis","Diffun","Maddela","Nagtipunan","Saguday"],
}
TOWN_LOOKUP = {t.lower(): (t, p) for p, ts in MUNICIPALITIES.items() for t in ts}

# Known messy variants seen in the data -> the clean town name to use for lookup
TOWN_ALIASES = {
    "cauayan city, isabela": "Cauayan City",
    "sto. niño (faire)": "Sto. Niño",
    "sto. nino (faire)": "Sto. Niño",
}


def clean_town(raw):
    t = str(raw).strip()
    key = t.lower()
    if key in TOWN_ALIASES:
        return TOWN_ALIASES[key]
    return t


if not os.path.exists(DB):
    print(f"'{DB}' not found in this folder."); raise SystemExit

# 1) backup first, always
ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
backup = f"telco_backup_{ts}.db"
shutil.copy(DB, backup)
print(f"Backup saved: {backup}")

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# 2) fix the Town/Barangay mix-up: Town blank, Barangay actually holds a town name
swap_fixed = 0
rows = conn.execute(
    "SELECT id, brgy FROM licenses WHERE (town IS NULL OR town='') "
    "AND brgy IS NOT NULL AND brgy <> '' AND deleted_at IS NULL").fetchall()
for r in rows:
    key = str(r["brgy"]).strip().lower()
    if key in TOWN_LOOKUP:
        real_town, _ = TOWN_LOOKUP[key]
        conn.execute("UPDATE licenses SET town = ?, brgy = NULL WHERE id = ?", (real_town, r["id"]))
        swap_fixed += 1
print(f"Fixed {swap_fixed} record(s) where Barangay held a town name (moved to Town).")

# 3) fill blank Province from Town, using the official mapping
prov_filled = 0
unmatched_towns = {}
rows = conn.execute(
    "SELECT id, town FROM licenses WHERE (province IS NULL OR province='') "
    "AND town IS NOT NULL AND town <> '' AND deleted_at IS NULL").fetchall()
for r in rows:
    t = clean_town(r["town"])
    key = t.lower()
    if key in TOWN_LOOKUP:
        _, prov = TOWN_LOOKUP[key]
        conn.execute("UPDATE licenses SET province = ? WHERE id = ?", (prov, r["id"]))
        prov_filled += 1
    else:
        unmatched_towns[r["town"]] = unmatched_towns.get(r["town"], 0) + 1

conn.commit()

# 4) needs-review counts (things this script deliberately did NOT invent)
missing_siteno = conn.execute(
    "SELECT COUNT(*) FROM licenses WHERE (site_no IS NULL OR site_no='') AND deleted_at IS NULL").fetchone()[0]
missing_addr = conn.execute(
    "SELECT COUNT(*) FROM licenses WHERE (address IS NULL OR address='') AND deleted_at IS NULL").fetchone()[0]
still_blank_province = conn.execute(
    "SELECT COUNT(*) FROM licenses WHERE (province IS NULL OR province='') AND deleted_at IS NULL").fetchone()[0]

conn.close()

print(f"Filled Province on {prov_filled} record(s) using their Town.")
print()
print("---- Needs a human (not auto-fixed) ----")
print(f"Still missing Province (town not recognized): {still_blank_province}")
if unmatched_towns:
    print("  Unrecognized town values found:")
    for t, c in sorted(unmatched_towns.items(), key=lambda x: -x[1]):
        print(f"    {t!r}: {c} record(s)")
print(f"Missing Site No.  : {missing_siteno} record(s) — needs the physical case file")
print(f"Missing Address   : {missing_addr} record(s) — needs the physical case file")
print()
print("Done. If anything looks wrong, restore from the backup file above.")
