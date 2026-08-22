"""
cleanup_frequency_range.py

A one-time cleanup tool for the "Frequency Range" field on your licenses.

Some records still carry old leftover text in the Frequency Range field
from the original import (the same value repeated across many records,
unrelated to what's actually in Frequency 1-4). This script shows you
every distinct value currently sitting in that field, how many records
have it, and lets you pick which ones to clear out -- nothing is changed
until you confirm.

A backup copy of telco.db is made automatically before anything is
touched, just in case.

HOW TO RUN:
  Double-click this file if .py files are set to open with Python, or
  open a command prompt in this folder and run:
      python cleanup_frequency_range.py
"""

import sqlite3
import shutil
import datetime
import os
import sys

DB_FILE = "telco.db"


def main():
    if not os.path.exists(DB_FILE):
        print(f'Could not find "{DB_FILE}" in this folder.')
        print("Run this script from the same folder as start.bat / telco.db.")
        input("\nPress Enter to close...")
        return

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        SELECT freq_range, COUNT(*) AS n
        FROM licenses
        WHERE freq_range IS NOT NULL AND TRIM(freq_range) != ''
        GROUP BY freq_range
        ORDER BY n DESC
        """
    ).fetchall()

    if not rows:
        print("No records currently have anything in the Frequency Range field.")
        print("Nothing to clean up.")
        input("\nPress Enter to close...")
        conn.close()
        return

    print("=" * 70)
    print("Frequency Range values currently in your database")
    print("=" * 70)
    print()
    for i, r in enumerate(rows, start=1):
        preview = r["freq_range"].replace("\n", " | ").replace("\t", "  ")
        if len(preview) > 60:
            preview = preview[:57] + "..."
        print(f"  [{i}] used in {r['n']:>4} record(s):  {preview}")
    print()
    print("If one value is used by a lot of records and doesn't look like a")
    print("real, specific frequency range for a site, that's almost certainly")
    print("the leftover junk from the import.")
    print()
    print("Type the number(s) of the value(s) you want to CLEAR (set blank),")
    print("separated by commas (e.g. 1  or  1,3). Type 0 to cancel and exit.")
    print()

    choice = input("Your choice: ").strip()
    if not choice or choice == "0":
        print("Cancelled -- nothing was changed.")
        conn.close()
        return

    try:
        picks = sorted(set(int(x.strip()) for x in choice.split(",") if x.strip()))
    except ValueError:
        print("Didn't understand that input -- nothing was changed. Run the script again.")
        conn.close()
        return

    valid_picks = [p for p in picks if 1 <= p <= len(rows)]
    if not valid_picks:
        print("No valid selections -- nothing was changed.")
        conn.close()
        return

    values_to_clear = [rows[p - 1]["freq_range"] for p in valid_picks]
    total_affected = sum(rows[p - 1]["n"] for p in valid_picks)

    print()
    print(f"About to clear the Frequency Range field on {total_affected} record(s).")
    confirm = input("Type YES to proceed: ").strip()
    if confirm.upper() != "YES":
        print("Cancelled -- nothing was changed.")
        conn.close()
        return

    conn.close()

    # Backup first
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"telco_backup_before_freqcleanup_{stamp}.db"
    shutil.copy2(DB_FILE, backup_name)
    print(f"\nBackup saved as: {backup_name}")

    # Now actually clear
    conn = sqlite3.connect(DB_FILE)
    updated = 0
    for v in values_to_clear:
        cur = conn.execute("UPDATE licenses SET freq_range = '' WHERE freq_range = ?", (v,))
        updated += cur.rowcount
    conn.commit()
    conn.close()

    print(f"\nDone. Cleared Frequency Range on {updated} record(s).")
    print("If anything looks wrong, restore from the backup file listed above.")
    input("\nPress Enter to close...")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nSomething went wrong: {e}")
        input("\nPress Enter to close...")
        sys.exit(1)
