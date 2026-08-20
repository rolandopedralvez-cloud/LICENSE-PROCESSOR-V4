"""
print_rsl_word.py  —  Preview / print an RSL using the Word template.

RUN THIS ON YOUR PC (needs Microsoft Word + pywin32). This is the test
script — same idea as print_rsl.py did for Excel: try it here first,
then we wire it into the app's Print buttons once it looks right.

Usage:
    python print_rsl_word.py preview 5      # preview record id 5
    python print_rsl_word.py print 5        # print record id 5
"""

import os
import sys
from app.legacy import print_stage_word

TEMPLATE_FILE = "RSL_Format_2025_mapped.docx"   # the template with all 50 fields
DB_FILE = "telco.db"

# Word field-type constant for a MERGEFIELD
WD_FIELD_MERGEFIELD = 59


def main():
    if len(sys.argv) < 3:
        print(__doc__); return
    mode = sys.argv[1].lower()
    try:
        lic_id = int(sys.argv[2])
    except ValueError:
        print("Record id must be a number."); return
    if mode not in ("preview", "print"):
        print("First argument must be 'preview' or 'print'."); return

    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root (was: this script's own folder) -- these files moved into app/legacy/ during the FastAPI restructuring, but the template/output files (PRINT_ready.xlsx, RSL_Format_2025_mapped.docx, telco.db, etc.) still live in the project root next to start.bat, not next to this .py file
    template_path = os.path.join(here, TEMPLATE_FILE)
    db_path = os.path.join(here, DB_FILE)
    if not os.path.exists(template_path):
        print(f"Cannot find {TEMPLATE_FILE} in this folder."); return

    rec = print_stage_word.fetch_record(db_path, lic_id)
    if not rec:
        print(f"Record {lic_id} not found."); return
    values = print_stage_word.word_field_values(rec)

    try:
        import win32com.client as win32
    except ImportError:
        print("pywin32 is not installed. Run:  pip install pywin32"); return

    # unblock if this file was downloaded (same Windows quirk as the Excel template)
    try:
        os.remove(template_path + ":Zone.Identifier")
    except OSError:
        pass

    word = win32.Dispatch("Word.Application")
    word.Visible = True
    doc = word.Documents.Open(template_path, ReadOnly=False)

    try:
        updated = 0
        missing = []
        def update_fields(fields):
            nonlocal updated
            for field in fields:
                try:
                    if field.Type != WD_FIELD_MERGEFIELD:
                        continue
                    code = field.Code.Text  # e.g. ' MERGEFIELD LicenseNo '
                    name = code.replace("MERGEFIELD", "").replace('"', "").replace('\u201c', "").replace('\u201d', "").strip()
                    if name in values:
                        field.Result.Text = values[name]
                        updated += 1
                    else:
                        missing.append(name)
                except Exception:
                    continue   # never let one broken field stop the rest

        # main body fields (rare on this template, but check anyway)
        update_fields(doc.Fields)
        # this template's fields all live inside floating text boxes, which
        # Word keeps in a SEPARATE collection from doc.Fields — visit each one,
        # recursing into any grouped shapes (a shape inside a Group isn't
        # directly reachable — only its top-level Group container is)
        MSO_GROUP = 6
        def walk_shapes(shapes):
            for shape in shapes:
                try:
                    if shape.Type == MSO_GROUP:
                        walk_shapes(shape.GroupItems)
                        continue
                except Exception:
                    pass
                try:
                    if shape.TextFrame.HasText:
                        update_fields(shape.TextFrame.TextRange.Fields)
                except Exception:
                    continue  # shapes with no text (e.g. the OR stamp picture)
        walk_shapes(doc.Shapes)

        print(f"Filled {updated} field(s).")
        if missing:
            print("Fields in the document with no matching value:", sorted(set(missing)))

        # force Word to fully repaint before showing the preview — sometimes
        # a field's stored result updates without the on-screen shape redrawing
        try:
            win = word.ActiveWindow
            win.View.ShowFieldCodes = True
            win.View.ShowFieldCodes = False
        except Exception:
            pass
        try:
            doc.Repaginate()
        except Exception:
            pass
        try:
            word.ScreenRefresh()
        except Exception:
            pass

        if mode == "preview":
            print("Opening print preview…")
            word.ActiveWindow.View.Type = 4  # wdPrintPreview
        else:
            print("Printing…")
            doc.PrintOut()
        print("Done. (Not saving changes to the template — it stays clean.)")
    finally:
        pass  # leave doc open so you can see the result / preview


if __name__ == "__main__":
    main()
