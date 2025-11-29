# features/debug_database.py
"""
Temporary admin-only DB inspector.

Usage: /debug (admin only)
Outputs:
 - DB path
 - whether DB file exists
 - users table schema (PRAGMA)
 - COUNT(*) from users
 - up to 20 values from the best-candidate user id column (guessed)
 - up to 10 sample rows (SELECT * LIMIT 10)

This feature is defensive: will not assume any column names and will not use Markdown parsing.
"""

import os
import sqlite3
import logging
from typing import List

from telegram import Update
from telegram.ext import CallbackContext, CommandHandler

import admins
import database

logger = logging.getLogger(__name__)


def _get_admin_ids() -> set:
    raw = getattr(admins, "ADMIN_IDS", None) or getattr(admins, "ADMINS", None) or []
    ids = set()
    for v in raw:
        try:
            ids.add(int(v))
        except Exception:
            logger.debug("Ignoring bad admin id %r", v)
    return ids


def _safe_connect(db_path: str):
    # Connect but don't fail loudly; caller will handle exceptions
    return sqlite3.connect(db_path, timeout=10)


def _table_info(conn: sqlite3.Connection, table: str) -> List[tuple]:
    cur = conn.execute(f"PRAGMA table_info({table});")
    return cur.fetchall()  # returns rows: (cid, name, type, notnull, dflt_value, pk)


def _guess_id_column(cols: List[tuple]) -> str:
    """
    Columns from PRAGMA: (cid, name, type, notnull, dflt_value, pk)
    Try to find candidate column to act as user_id:
      1) exact name 'user_id'
      2) any column named 'id'
      3) any integer primary key (pk > 0)
      4) first integer-typed column
      5) fallback to first column
    """
    if not cols:
        return None
    names = [c[1] for c in cols]
    # 1
    if "user_id" in names:
        return "user_id"
    # 2
    if "id" in names:
        return "id"
    # 3
    for c in cols:
        cid, name, typ, notnull, dflt, pk = c
        if pk and pk > 0:
            return name
    # 4
    for c in cols:
        cid, name, typ, notnull, dflt, pk = c
        if typ and ("INT" in typ.upper() or "INTEGER" in typ.upper()):
            return name
    # 5
    return cols[0][1]


def debug_handler(update: Update, context: CallbackContext):
    user = update.effective_user
    if not user:
        return

    if user.id not in _get_admin_ids():
        logger.info("Non-admin %s tried /debug", user.id)
        return

    DB_PATH = getattr(database, "DB_PATH", None) or os.getenv("DB_PATH") or os.getenv("SQLITE_PATH") or "/data/data.db"
    text_lines = []
    text_lines.append(f"DB path: {DB_PATH!r}")
    text_lines.append(f"DB file exists: {'yes' if os.path.exists(DB_PATH) else 'no'}")

    try:
        conn = _safe_connect(DB_PATH)
    except Exception as e:
        logger.exception("Failed to connect to DB %s: %s", DB_PATH, e)
        update.message.reply_text(f"Failed to open DB: {e}")
        return

    try:
        # Check if users table exists
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users';")
        has_users = cur.fetchone() is not None
        text_lines.append(f"Has table 'users': {'yes' if has_users else 'no'}")

        if not has_users:
            # show available tables
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
            tables = [r[0] for r in cur.fetchall()]
            text_lines.append("Other tables: " + (", ".join(tables) if tables else "(none)"))
            update.message.reply_text("\n".join(text_lines))
            return

        # Table info
        try:
            cols = _table_info(conn, "users")
            if cols:
                text_lines.append("users table schema (cid, name, type, notnull, dflt_value, pk):")
                for c in cols:
                    text_lines.append(str(c))
            else:
                text_lines.append("users table schema: (no columns returned)")
        except Exception as e:
            logger.exception("PRAGMA table_info failed: %s", e)
            text_lines.append(f"Failed to get schema: {e}")

        # Count rows
        try:
            cur = conn.execute("SELECT COUNT(*) FROM users;")
            r = cur.fetchone()
            count = int(r[0]) if r else 0
            text_lines.append(f"COUNT(*) from users -> {count}")
        except Exception as e:
            logger.exception("COUNT(*) failed: %s", e)
            text_lines.append(f"COUNT(*) failed: {e}")

        # Guess id column and fetch up to 20 values
        try:
            id_col = _guess_id_column(cols)
            if id_col:
                safe_col = '"' + id_col.replace('"', '""') + '"'
                cur = conn.execute(f"SELECT {safe_col} FROM users LIMIT 20;")
                vals = [str(r[0]) for r in cur.fetchall() if r and r[0] is not None]
                text_lines.append(f"Guessed id column: {id_col!r}; sample (up to 20):")
                text_lines.append(", ".join(vals) if vals else "(no values)")
            else:
                text_lines.append("Could not guess id column.")
        except Exception as e:
            logger.exception("Failed to fetch sample ids: %s", e)
            text_lines.append(f"Failed to fetch sample ids: {e}")

        # Fetch sample rows (SELECT * LIMIT 10)
        try:
            cur = conn.execute("SELECT * FROM users LIMIT 10;")
            rows = cur.fetchall()
            if rows:
                # column names
                col_names = [d[0] for d in cur.description]
                text_lines.append("Sample rows (up to 10). Columns: " + ", ".join(col_names))
                for row in rows:
                    # convert each value to string safely
                    row_str = []
                    for v in row:
                        if v is None:
                            row_str.append("NULL")
                        else:
                            # limit length to avoid giant dumps
                            s = str(v)
                            if len(s) > 160:
                                s = s[:157] + "..."
                            row_str.append(s.replace("\n", "\\n"))
                    text_lines.append("; ".join(row_str))
            else:
                text_lines.append("Sample rows: (none)")
        except Exception as e:
            logger.exception("Failed to fetch sample rows: %s", e)
            text_lines.append(f"Failed to fetch sample rows: {e}")

    finally:
        try:
            conn.close()
        except Exception:
            pass

    # send as plain text (no Markdown) to avoid parse errors
    reply = "\n\n".join(text_lines)
    try:
        update.message.reply_text(reply)
    except Exception as e:
        logger.exception("Failed to send debug reply: %s", e)
        try:
            update.message.reply_text("Failed to send debug reply; check logs.")
        except Exception:
            pass


def setup(dispatcher):
    dispatcher.add_handler(CommandHandler("debug", debug_handler))
    logger.info("debug_database feature loaded. Admins=%r DB=%r", _get_admin_ids(), getattr(database, "DB_PATH", None))
