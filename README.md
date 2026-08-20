# NTC Telco Licensing App

A local desktop/web app for managing NTC Region II telco license records (SQLite-backed), with search, editing, and Excel/Word print templates for RSL documents.

## Setup (Windows)

1. Install Python 3.
2. Open Command Prompt in this folder and run:
   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Create the database (first time only):
   ```
   python create_db.py
   ```
4. Load your Excel data (first time only, needs `TELCO_DATABASE_FINAL.xlsx` in this folder):
   ```
   python migrate.py
   ```
5. Set up a login:
   ```
   python set_login.py
   ```

## Running the app

- Double-click `start.bat`, or
- Double-click `NTC.vbs` for a windowless launch (uses `desktop.py`).

The app runs at `http://127.0.0.1:8000`.

## Files

- `create_db.py` — creates the empty SQLite database (`telco.db`).
- `migrate.py` — one-time import from the Excel workbook into the database.
- `main.py` / `main_updated.py` — the FastAPI backend/app.
- `index.html` — the web front end.
- `set_login.py` — create/change app login credentials.
- `fix_license_status.py`, `fix_province.py` — one-off data-cleanup scripts.
- `print_engine.py`, `print_rsl.py`, `print_stage.py` — Excel-based RSL printing.
- `print_engine_word.py`, `print_rsl_word.py`, `print_stage_word.py` — Word-based RSL printing.
- `start.bat`, `NTC.vbs` — app launchers.

## Notes

- `telco.db` and any `telco_backup_*.db` files are not tracked in git (see `.gitignore`) since they contain live data.
- Printing features require Microsoft Excel/Word and `pywin32`, and must be run on Windows.
