"""
set_login.py  —  Create or change the app's login credential.

Run:  python set_login.py
Then type a username and password. The password is stored HASHED (never in
plain text). Run it again anytime to change the login or add another user.
"""

import sqlite3
import os
import hashlib
import secrets
import getpass

DB = "telco.db"
PBKDF_ROUNDS = 200_000

if not os.path.exists(DB):
    print(f"'{DB}' not found in this folder."); raise SystemExit

conn = sqlite3.connect(DB)
conn.execute("""CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY,
    salt     BLOB NOT NULL,
    pwhash   BLOB NOT NULL
);""")
# make sure the role column exists
cols = [r[1] for r in conn.execute("PRAGMA table_info(users)")]
if "role" not in cols:
    conn.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'admin';")

username = input("Username: ").strip()
if not username:
    print("Username cannot be empty."); raise SystemExit

print("Role:  [1] master  (full access, can delete)")
print("       [2] field   (can add and edit, CANNOT delete)")
choice = input("Choose role 1 or 2 [1]: ").strip()
role = "user" if choice == "2" else "admin"

# getpass hides typing; if your terminal doesn't support it, it still works
pw1 = getpass.getpass("Password: ")
pw2 = getpass.getpass("Confirm password: ")
if pw1 != pw2:
    print("Passwords do not match. Nothing changed."); raise SystemExit
if len(pw1) < 4:
    print("Please use at least 4 characters."); raise SystemExit

salt = secrets.token_bytes(16)
pwhash = hashlib.pbkdf2_hmac("sha256", pw1.encode("utf-8"), salt, PBKDF_ROUNDS)

conn.execute(
    "INSERT INTO users (username, salt, pwhash, role) VALUES (?, ?, ?, ?) "
    "ON CONFLICT(username) DO UPDATE SET salt=excluded.salt, pwhash=excluded.pwhash, role=excluded.role",
    (username, salt, pwhash, role),
)
conn.commit()
conn.close()
label = "master (full access)" if role == "admin" else "field (add/edit only, no delete)"
print(f"Saved login for '{username}' as {label}.")
