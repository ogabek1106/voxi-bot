# features/user_migration.py
"""
Feature: debug + import old user IDs into SQLite users table.

Place in features/ and deploy. Use these admin commands:
- /import_users   -> searches for JSON backups and imports IDs into DB
- /dump_users N   -> shows up to N sample rows from users table (admin-only)
- /count_users    -> prints current count (admin-only)

Uses DB_PATH env var (falls back to /data/data.db).
Reads possible sources:
 - user_ids.json (root)
 - user_ids.json.txt (root)
 - old files/user_ids.json.txt
 - user_ids.json inside old files folder, etc.

Inserts using INSERT OR IGNORE into table `users(user_id, first_name, username, added_at)`.
"""

import os
import json
import time
import sqlite3
import logging
from typing import List, Set

from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

import admins

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))

# possible backup filenames to check (in repo root and "old files/" folder)
POSSIBLE_FILES = [
    "user_ids.json",
    "user_ids.json.txt",
    "user_ids.jsonl",
    "user_ids.jsonl.txt",
    "old files/user_ids.json",
    "old files/user_ids.json.txt",
    "user_ids.txt",
    "user_ids.json.txt"
]


def _ensure_users_table():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            added_at INTEGER
        );
        """)
        conn.commit()
    finally:
        conn.close()


def _count_users_db() -> int:
    if not os.path.exists(DB_PATH):
        return 0
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        cur = conn.execute("SELECT COUNT(*) FROM users;")
        r = cur.fetchone()
        return int(r[0]) if r else 0
    finally:
        conn.close()


def _sample_users(limit: int = 10) -> List[tuple]:
    if not os.path.exists(DB_PATH):
        return []
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        cur = conn.execute("SELECT user_id, first_name, username, datetime(added_at,'unixepoch') FROM users ORDER BY added_at DESC LIMIT ?;", (limit,))
        return cur.fetchall()
    finally:
        conn.close()


def _load_ids_from_file(path: str) -> Set[int]:
    """Try to load integers from a JSON array, dict, or lines. Return set of ints."""
    results = set()
    if not os.path.exists(path):
        return results
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = f.read()
            # try JSON
            try:
                parsed = json.loads(data)
                # if it's a dict with user ids as keys or list of ids
                if isinstance(parsed, dict):
                    for k in parsed.keys():
                        try:
                            results.add(int(k))
                        except Exception:
                            pass
                elif isinstance(parsed, list):
                    for item in parsed:
                        try:
                            # item could be int or dict with id
                            if isinstance(item, dict) and "id" in item:
                                results.add(int(item["id"]))
                            else:
                                results.add(int(item))
                        except Exception:
                            pass
            except Exception:
                # fallback: try parse as newline-separated ints
                for line in data.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        # handle possible "12345: name" formats
                        part = line.split()[0].strip().strip(",")
                        results.add(int(part))
                    except Exception:
                        continue
    except Exception as e:
        logger.exception("Failed to read file %s: %s", path, e)
    return results


def _import_user_ids(ids: Set[int]) -> int:
    """Insert ids into DB users table. Returns number inserted."""
    if not ids:
        return 0
    _ensure_users_table()
    conn = sqlite3.connect(DB_PATH, timeout=10)
    inserted = 0
    try:
        cur = conn.cursor()
        now = int(time.time())
        for uid in ids:
            try:
                cur.execute("INSERT OR IGNORE INTO users (user_id, first_name, username, added_at) VALUES (?, ?, ?, ?);", (int(uid), None, None, now))
                if cur.rowcount == 1:
                    inserted += 1
            except Exception:
                # skip bad IDs
                continue
        conn.commit()
    finally:
        conn.close()
    return inserted


def _gather_possible_ids() -> Set[int]:
    found = set()
    # check each candidate path
    for fname in POSSIBLE_FILES:
        # check absolute and relative
        for p in (fname, os.path.join("old files", os.path.basename(fname))):
            if os.path.exists(p):
                ids = _load_ids_from_file(p)
                if ids:
                    logger.info("Found %d IDs in file %s", len(ids), p)
                    found.update(ids)
    # also check for literal user_ids.json in repository root
    if os.path.exists("user_ids.json"):
        found.update(_load_ids_from_file("user_ids.json"))
    # also check "user_ids.json.txt" in root
    if os.path.exists("user_ids.json.txt"):
        found.update(_load_ids_from_file("user_ids.json.txt"))
    return found


def _is_admin(user_id: int) -> bool:
    raw = getattr(admins, "ADMIN_IDS", set())
    try:
        return int(user_id) in {int(x) for x in raw}
    except Exception:
        return False


# ---- command handlers ----

def import_users_cmd(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        return
    update.message.reply_text("Starting import: scanning possible backup files...")
    # gather possible IDs
    ids = _gather_possible_ids()
    if not ids:
        update.message.reply_text("No backup user-id files found in repo (checked common locations).")
        return
    before = _count_users_db()
    inserted = _import_user_ids(ids)
    after = _count_users_db()
    update.message.reply_text(f"Imported {inserted} IDs. Count before: {before} → after: {after}")


def dump_users_cmd(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        return
    sample = _sample_users(limit=20)
    if not sample:
        update.message.reply_text("No users found in DB.")
        return
    text_lines = ["Sample users (user_id | first_name | username | added_at):"]
    for row in sample:
        text_lines.append(" | ".join(str(x) for x in row))
    update.message.reply_text("\n".join(text_lines))


def count_users_cmd(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user or not _is_admin(user.id):
        return
    c = _count_users_db()
    update.message.reply_text(f"👥 Unique users (total): {c}")


def setup(dispatcher, bot=None):
    # register admin-only commands
    dispatcher.add_handler(CommandHandler("import_users", import_users_cmd))
    dispatcher.add_handler(CommandHandler("dump_users", dump_users_cmd))
    dispatcher.add_handler(CommandHandler("count_users", count_users_cmd))
    logger.info("user_migration feature loaded. DB_PATH=%s", DB_PATH)
