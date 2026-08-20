"""
print_rsl.py  —  Preview / print RSLs straight from the database.

Self-contained: writes each record into the internal STAGING sheet of
PRINT_ready.xlsx (row 2), which FRONT reads. No external file, no links.

RUN THIS ON YOUR PC (needs Excel + pywin32).

Usage:
    python print_rsl.py preview 5          # preview record id 5
    python print_rsl.py print 5            # print record id 5
    python print_rsl.py print 5 12 33 40   # batch print several
"""

import os
import sys
import time
from app.legacy import print_stage

# ---------------- settings ----------------
PRINT_FILE = "PRINT_ready.xlsx"          # the surgically-prepared print file
DB_FILE = "telco.db"
SHEETS_TO_PRINT = ["FRONT"]              # add "BACK" once FRONT looks right
# ------------------------------------------


def main():
    if len(sys.argv) < 3:
        print(__doc__); return
    mode = sys.argv[1].lower()
    ids = [int(x) for x in sys.argv[2:]]
    if mode not in ("preview", "print"):
        print("First argument must be 'preview' or 'print'."); return

    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root (was: this script's own folder) -- these files moved into app/legacy/ during the FastAPI restructuring, but the template/output files (PRINT_ready.xlsx, RSL_Format_2025_mapped.docx, telco.db, etc.) still live in the project root next to start.bat, not next to this .py file
    print_path = os.path.join(here, PRINT_FILE)
    db_path = os.path.join(here, DB_FILE)
    if not os.path.exists(print_path):
        print(f"Cannot find {PRINT_FILE} in this folder."); return

    try:
        import win32com.client as win32
    except ImportError:
        print("pywin32 is not installed. Run:  pip install pywin32"); return

    # Windows blocks files downloaded from the internet ("Mark of the Web"),
    # which makes Excel open them in Protected View and breaks automation.
    # Remove that tag so Excel can open it normally.
    try:
        os.remove(print_path + ":Zone.Identifier")
        print("(unblocked the print file)")
    except OSError:
        pass

    excel = win32.Dispatch("Excel.Application")
    excel.Visible = True
    excel.DisplayAlerts = False
    try:
        # UpdateLinks=0 = don't try to refresh the old external link on open
        wb = excel.Workbooks.Open(print_path, UpdateLinks=0)
    except Exception as e:
        print("Could not open the print file. Most common cause: the file is")
        print("still blocked by Windows. Right-click PRINT_ready.xlsx -> Properties")
        print("-> tick 'Unblock' -> OK, then run again.")
        print("Raw error:", e)
        return
    stage = wb.Sheets(print_stage.STAGING_SHEET)

    try:
        for n, lic_id in enumerate(ids, start=1):
            rec = print_stage.fetch_record(db_path, lic_id)
            if not rec:
                print(f"  record {lic_id}: not found, skipping"); continue

            # clear staging row 2, then write this record's cells
            stage.Range(f"A{print_stage.STAGING_ROW}:BG{print_stage.STAGING_ROW}").ClearContents()
            for col, value in print_stage.staging_cells(rec):
                stage.Cells(print_stage.STAGING_ROW, col).Value = value

            excel.CalculateFull()
            time.sleep(0.2)

            for sheet_name in SHEETS_TO_PRINT:
                ws = wb.Sheets(sheet_name)
                if mode == "preview":
                    print(f"  preview {lic_id} ({n}/{len(ids)}) - {sheet_name}")
                    ws.PrintPreview()          # close the preview to continue
                else:
                    print(f"  print {lic_id} ({n}/{len(ids)}) - {sheet_name}")
                    ws.PrintOut()
        print("Done. (Template left unsaved so it stays clean.)")
    finally:
        excel.DisplayAlerts = True


if __name__ == "__main__":
    main()
