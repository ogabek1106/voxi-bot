# database.py
"""
Central SQLite utilities for Voxi bot.

Place this file in repo root as `database.py` and treat it as an immutable core helper.
Functions:
 - ensure_db()
 - add_user_if_new(user_id, first_name, username) -> bool
 - get_all_users(as_rows=False) -> list
 - get_user_count() -> int
 - sample_users(limit=10) -> list
"""

import os
import sqlite3
import time
import logging
from typing import Optional, List, Tuple, Union

logger = logging.getLogger(__name__)

# prefer DB_PATH (Railway variable). fallback to SQLITE_PATH, then local default in container
DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))

# SQLite busy timeout (seconds)
SQLITE_TIMEOUT = 10


def _connect():
    """Open a short-lived SQLite connection with reasonable timeout."""
    # ensure folder exists
    dirname = os.path.dirname(DB_PATH)
    try:
        if dirname and not os.path.exists(dirname):
            os.makedirs(dirname, exist_ok=True)
    except Exception as e:
        logger.debug("Could not ensure DB directory exists: %s", e)
    conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT)
    return conn


def ensure_db():
    """Create necessary tables if they don't exist. Safe to call multiple times."""
    conn = _connect()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT,
                username TEXT,
                added_at INTEGER
            );
            """
        )
        conn.commit()
    except Exception as e:
        logger.exception("Failed to ensure DB schema: %s", e)
    finally:
        conn.close()


def add_user_if_new(user_id: int, first_name: Optional[str] = None, username: Optional[str] = None) -> bool:
    """
    Insert a user if not exists.
    Returns True if inserted (new), False if already present.
    """
    ensure_db()
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO users (user_id, first_name, username, added_at) VALUES (?, ?, ?, ?);",
            (int(user_id), first_name, username, int(time.time())),
        )
        conn.commit()
        inserted = cur.rowcount == 1
        if inserted:
            logger.info("New user added to DB: %s (%s / @%s)", user_id, first_name, username)
        return bool(inserted)
    except Exception as e:
        logger.exception("Failed to add user %s: %s", user_id, e)
        return False
    finally:
        conn.close()


def get_all_users(as_rows: bool = False) -> List[Union[int, Tuple]]:
    """
    Return list of users.
    - as_rows=False -> [user_id, ...]
    - as_rows=True  -> [(user_id, first_name, username, added_at), ...]
    """
    if not os.path.exists(DB_PATH):
        return []
    conn = _connect()
    try:
        if as_rows:
            cur = conn.execute("SELECT user_id, first_name, username, added_at FROM users ORDER BY added_at DESC;")
            rows = cur.fetchall()
            return rows
        else:
            cur = conn.execute("SELECT user_id FROM users ORDER BY added_at DESC;")
            rows = cur.fetchall()
            return [int(r[0]) for r in rows]
    except Exception as e:
        logger.exception("Failed to fetch users: %s", e)
        return []
    finally:
        conn.close()


def get_user_count() -> int:
    """Return the total number of users in the DB (0 if missing)."""
    if not os.path.exists(DB_PATH):
        return 0
    conn = _connect()
    try:
        cur = conn.execute("SELECT COUNT(*) FROM users;")
        r = cur.fetchone()
        return int(r[0]) if r else 0
    except Exception as e:
        logger.exception("Failed to count users: %s", e)
        return 0
    finally:
        conn.close()


def sample_users(limit: int = 10) -> List[Tuple]:
    """Return a few rows for inspection (admin debugging)."""
    if not os.path.exists(DB_PATH):
        return []
    conn = _connect()
    try:
        cur = conn.execute(
            "SELECT user_id, first_name, username, datetime(added_at, 'unixepoch') FROM users ORDER BY added_at DESC LIMIT ?;",
            (limit,),
        )
        return cur.fetchall()
    except Exception as e:
        logger.exception("Failed to sample users: %s", e)
        return []
    finally:
        conn.close()


# Run ensure_db on import so features can rely on table being present
ensure_db()
