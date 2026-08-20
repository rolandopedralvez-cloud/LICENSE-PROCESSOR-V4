"""One-off script used during the FastAPI restructuring (step 3 of
MODERNIZATION_PLAN.md) to mechanically slice main.py into app/routers/*.py
files. Not part of the running app - kept here for provenance / re-run if
needed. Safe to delete once the restructuring is fully verified.
"""
import re

SRC = "/tmp/ntc/main.py"
lines = open(SRC, encoding="utf-8").read().splitlines(keepends=True)

def block(a, b):
    # 1-indexed inclusive main.py line numbers -> text
    return "".join(lines[a-1:b])

SEGMENTS = {
    "app/core.py": [(32, 318)],
    "app/routers/auth.py": [(320, 477)],
    "app/routers/settings.py": [(478, 612)],
    "app/routers/users.py": [(613, 803)],
    "app/routers/pages.py": [(854, 862)],
    "app/routers/licenses.py": [(882, 908), (928, 1157), (1245, 1353), (2570, 2614)],
    "app/routers/trash.py": [(1158, 1244)],
    "app/routers/analytics.py": [(863, 881), (909, 927), (1354, 1802)],
    "app/routers/print.py": [(1803, 1860)],
    "app/routers/import_.py": [(1861, 2320)],
    "app/routers/scan.py": [(2321, 2569)],
}

for path, ranges in SEGMENTS.items():
    text = "\n".join(block(a, b).rstrip("\n") for a, b in ranges)
    with open(f"/tmp/ntc/{path}.raw", "w", encoding="utf-8") as f:
        f.write(text + "\n")

print("done")
