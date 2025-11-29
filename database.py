# database.py
"""
Central SQLite utilities for Voxi bot.

Stable API (unchanged):
 - ensure_db()
 - add_user_if_new(user_id, first_name=None, username=None) -> bool
 - user_exists(user_id) -> bool
 - delete_user(user_id) -> bool
 - get_all_users(as_rows=False) -> list
 - get_all_users_in_chunks(chunk_size=1000) -> generator
 - get_user_count() -> int
 - sample_users(limit=10) -> list
 - migrate_from_list(list_of_ids_or_dicts) -> int
"""

from typing import Optional, List, Tuple, Union, Generator, Iterable
import os
import sqlite3
import time
import logging

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))
SQLITE_TIMEOUT = 5  # keep short to avoid blocking startup

# Minimal pragmas — applied if possible but never block startup
_PRAGMAS = [
    ("journal_mode", "WAL"),
    ("synchronous", "NORMAL"),
]


def _ensure_db_dir():
    """Best-effort create DB directory. Do not fail on error."""
    dirname = os.path.dirname(DB_PATH)
    if not dirname:
        return
    try:
        if not os.path.exists(dirname):
            os.makedirs(dirname, exist_ok=True)
            logger.debug("Created DB directory %s", dirname)
    except Exception as e:
        logger.debug("Could not ensure DB directory exists %s: %s", dirname, e)


def _connect():
    """
    Create a sqlite3 connection with a conservative timeout.
    Caller must close the connection.
    """
    _ensure_db_dir()
    try:
        conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT, check_same_thread=False)
    except Exception as e:
        logger.exception("sqlite3.connect failed: %s", e)
        raise

    # Try to apply a couple of safe pragmas — if it fails, continue.
    try:
        cur = conn.cursor()
        for key, val in _PRAGMAS:
            try:
                # Try unquoted (number-like) then quoted.
                cur.execute(f"PRAGMA {key} = {val};")
            except Exception:
                try:
                    cur.execute(f"PRAGMA {key} = '{val}';")
                except Exception:
                    logger.debug("Could not set PRAGMA %s=%s", key, val)
        cur.close()
    except Exception as e:
        logger.debug("Failed to set PRAGMAs (non-fatal): %s", e)

    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    try:
        cur = conn.execute(f"PRAGMA table_info({table});")
        rows = cur.fetchall()
        return [r[1] for r in rows] if rows else []
    except Exception as e:
        logger.debug("Failed to read table_info for %s: %s", table, e)
        return []


def ensure_db():
    """
    Ensure users table exists. Quick and non-blocking where possible.
    If columns are missing, attempt to ALTER TABLE ADD COLUMN (non-destructive).
    Any errors are logged and ignored so the process can continue.
    """
    logger.debug("ensure_db: starting (DB_PATH=%s)", DB_PATH)
    _ensure_db_dir()

    try:
        conn = _connect()
    except Exception:
        logger.exception("ensure_db: cannot open DB connection; skipping ensure.")
        return

    try:
        # Create table if missing (fast)
        with conn:
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

        # Inspect columns and add missing ones (best-effort)
        cols = _table_columns(conn, "users")
        required = {"first_name": "TEXT", "username": "TEXT", "added_at": "INTEGER"}
        missing = [c for c in required.keys() if c not in cols]
        if missing:
            logger.info("ensure_db: users table missing columns %s; attempting ALTER TABLE (best-effort)", missing)
            for c in missing:
                try:
                    with conn:
                        conn.execute(f"ALTER TABLE users ADD COLUMN {c} {required[c]};")
                        logger.info("ensure_db: added column %s", c)
                except Exception as e:
                    # log but don't stop startup
                    logger.warning("ensure_db: failed to add column %s: %s", c, e)
    except Exception as e:
        logger.exception("ensure_db: unexpected error: %s", e)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    logger.debug("ensure_db: finished")


def add_user_if_new(user_id: int, first_name: Optional[str] = None, username: Optional[str] = None) -> bool:
    ensure_db()
    conn = None
    try:
        conn = _connect()
        with conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO users (user_id, first_name, username, added_at) VALUES (?, ?, ?, ?);",
                (int(user_id), first_name, username, int(time.time())),
            )
            inserted = cur.rowcount == 1
            if inserted:
                logger.info("New user added: %s (%s / @%s)", user_id, first_name, username)
            return bool(inserted)
    except Exception as e:
        logger.exception("add_user_if_new failed for %s: %s", user_id, e)
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def user_exists(user_id: int) -> bool:
    if not os.path.exists(DB_PATH):
        return False
    conn = None
    try:
        conn = _connect()
        cur = conn.execute("SELECT 1 FROM users WHERE user_id = ? LIMIT 1;", (int(user_id),))
        return cur.fetchone() is not None
    except Exception as e:
        logger.exception("user_exists failed for %s: %s", user_id, e)
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def delete_user(user_id: int) -> bool:
    if not os.path.exists(DB_PATH):
        return False
    conn = None
    try:
        conn = _connect()
        with conn:
            cur = conn.execute("DELETE FROM users WHERE user_id = ?;", (int(user_id),))
            return cur.rowcount > 0
    except Exception as e:
        logger.exception("delete_user failed for %s: %s", user_id, e)
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_all_users(as_rows: bool = False) -> List[Union[int, Tuple]]:
    if not os.path.exists(DB_PATH):
        return []
    conn = None
    try:
        conn = _connect()
        cols = _table_columns(conn, "users")
        order_by = "added_at DESC" if "added_at" in cols else "user_id DESC"

        if as_rows:
            select_cols = []
            for c in ("user_id", "first_name", "username", "added_at"):
                if c in cols:
                    select_cols.append(c)
                else:
                    select_cols.append(f"NULL AS {c}")
            sql = "SELECT " + ", ".join(select_cols) + f" FROM users ORDER BY {order_by};"
            cur = conn.execute(sql)
            return cur.fetchall()
        else:
            if "user_id" in cols:
                cur = conn.execute(f"SELECT user_id FROM users ORDER BY {order_by};")
                return [int(r[0]) for r in cur.fetchall()]
            else:
                cur = conn.execute("SELECT * FROM users;")
                rows = cur.fetchall()
                ids = []
                for r in rows:
                    if r:
                        try:
                            ids.append(int(r[0]))
                        except Exception:
                            continue
                return ids
    except Exception as e:
        logger.exception("get_all_users failed: %s", e)
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_all_users_in_chunks(chunk_size: int = 1000) -> Generator[List[int], None, None]:
    if not os.path.exists(DB_PATH):
        return
        yield
    conn = None
    try:
        conn = _connect()
        cols = _table_columns(conn, "users")
        order_by = "added_at DESC" if "added_at" in cols else "user_id DESC"
        offset = 0
        while True:
            cur = conn.execute(f"SELECT user_id FROM users ORDER BY {order_by} LIMIT ? OFFSET ?;", (chunk_size, offset))
            rows = cur.fetchall()
            if not rows:
                break
            yield [int(r[0]) for r in rows]
            offset += len(rows)
    except Exception as e:
        logger.exception("get_all_users_in_chunks failed: %s", e)
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_user_count() -> int:
    if not os.path.exists(DB_PATH):
        return 0
    conn = None
    try:
        conn = _connect()
        cur = conn.execute("SELECT COUNT(*) FROM users;")
        r = cur.fetchone()
        return int(r[0]) if r else 0
    except Exception as e:
        logger.exception("get_user_count failed: %s", e)
        return 0
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def sample_users(limit: int = 10) -> List[Tuple]:
    if not os.path.exists(DB_PATH):
        return []
    conn = None
    try:
        conn = _connect()
        cols = _table_columns(conn, "users")
        select_cols = []
        out_cols = []
        if "user_id" in cols:
            select_cols.append("user_id"); out_cols.append("user_id")
        if "first_name" in cols:
            select_cols.append("first_name"); out_cols.append("first_name")
        if "username" in cols:
            select_cols.append("username"); out_cols.append("username")
        if "added_at" in cols:
            select_cols.append("added_at"); out_cols.append("added_at")

        if select_cols:
            sql = "SELECT " + ", ".join(select_cols) + " FROM users ORDER BY " + ("added_at" if "added_at" in cols else "user_id") + " DESC LIMIT ?;"
            cur = conn.execute(sql, (limit,))
            rows = cur.fetchall()
            out = []
            for r in rows:
                tup = list(r)
                if "added_at" in out_cols:
                    try:
                        idx = out_cols.index("added_at")
                        val = tup[idx]
                        if val is not None:
                            tup[idx] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(val)))
                    except Exception:
                        pass
                out.append(tuple(tup))
            return out
        else:
            cur = conn.execute("SELECT * FROM users LIMIT ?;", (limit,))
            return cur.fetchall()
    except Exception as e:
        logger.exception("sample_users failed: %s", e)
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def migrate_from_list(items: Iterable[Union[int, dict]]) -> int:
    added = 0
    for item in items:
        try:
            if isinstance(item, dict):
                uid = int(item.get("user_id") or item.get("id"))
                fn = item.get("first_name")
                un = item.get("username")
            else:
                uid = int(item)
                fn = None
                un = None
            if add_user_if_new(uid, fn, un):
                added += 1
        except Exception:
            logger.debug("Skipping bad migrate item: %r", item)
    logger.info("migrate_from_list: added %s new users", added)
    return added


# ensure DB quickly on import (best-effort)
ensure_db()
