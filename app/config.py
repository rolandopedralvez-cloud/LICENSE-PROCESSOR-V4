"""
app/config.py — central place for constants that used to be scattered as
module-level globals across main.py.
"""
import os

# Same relative path main.py always used ("telco.db" next to the process's
# working directory) — kept identical so no data migration is needed.
DB = os.environ.get("NTC_DB_PATH", "telco.db")
