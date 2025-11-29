# database.py
"""
Central SQLite utilities for Voxi bot.

Treat this file as the single immutable core DB helper used by all features.
All features MUST use functions in this module to read/write user data.

Exported functions (stable API):
 - ensure_db()
 - add_user_if_new(user_id, first_name=None, username=None) -> bool
 - user_exists(user_id) -> bool
 - delete_user(user_id) -> bool
 - get_all_users(as_rows=False) -> list
 - get_all_users_in_chunks(chunk_size=1000) -> generator of lists
 - get_user_count() -> int
 - sample_users(limit=10) -> list
 - migrate_from_list(list_of_ids_or_dicts) -> int (number added)
"""

from typing import Optional, List, Tuple, Union, Generator, Iterable
import os
import sqlite3
import time
import logging

logger = logging.getLogger(__name__)

# canonical DB path (use Railway env var DB_PATH or fallback to SQLITE_PATH, else /data/data.db)
DB_PATH = os.getenv("DB_PATH", os.getenv("SQLITE_PATH", "/data/data.db"))
SQLITE_TIMEOUT = 10  # seconds

# sqlite pragmas we set on each connection for better concurrency on hosted volumes
_PRAGMAS = [
    ("journal_mode", "WAL"),
    ("synchronous", "NORMAL"),
]


def _ensure_db_dir():
    """Create DB directory if it doesn't exist (best effort)."""
    dirname = os.path.dirname(DB_PATH)
    try:
        if dirname and not os.path.exists(dirname):
            os.makedirs(dirname, exist_ok=True)
    except Exception as e:
        logger.debug("Could not ensure DB directory exists: %s", e)


def _connect():
    """
    Create and return a new sqlite3.Connection with configured timeout and pragmas.
    Caller is responsible for closing the connection (use context manager).
    """
    _ensure_db_dir()
    conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT, check_same_thread=False)
    # apply pragmatic settings for better concurrent access
    try:
        cur = conn.cursor()
        for key, val in _PRAGMAS:
            try:
                cur.execute(f"PRAGMA {key} = {val};")
            except Exception:
                try:
                    cur.execute(f"PRAGMA {key} = '{val}';")
                except Exception:
                    logger.debug("Could not set PRAGMA %s=%s", key, val)
        cur.close()
    except Exception as e:
        logger.debug("Failed to set pragmas on DB connection: %s", e)
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    """Return list of column names for table (empty list if no table or error)."""
    try:
        cur = conn.execute(f"PRAGMA table_info({table});")
        rows = cur.fetchall()
        return [r[1] for r in rows] if rows else []
    except Exception as e:
        logger.debug("Failed to read table_info for %s: %s", table, e)
        return []


def ensure_db():
    """
    Create necessary tables if they don't exist. Safe to call multiple times.
    Creates a single `users` table:
      - user_id INTEGER PRIMARY KEY
      - first_name TEXT
      - username TEXT
      - added_at INTEGER (unix epoch)
    If table exists but lacks columns, attempt to ALTER TABLE ADD COLUMN (non-destructive).
    """
    _ensure_db_dir()
    conn = _connect()
    try:
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

        # inspect columns and add missing ones if needed
        cols = _table_columns(conn, "users")
        required = {
            "first_name": "TEXT",
            "username": "TEXT",
            "added_at": "INTEGER",
        }
        missing = [c for c in required.keys() if c not in cols]
        if missing:
            logger.info("users table missing columns %s; attempting ALTER TABLE to add them.", missing)
            try:
                for c in missing:
                    with conn:
                        conn.execute(f"ALTER TABLE users ADD COLUMN {c} {required[c]};")
                        logger.info("Added column %s to users table", c)
            except Exception as e:
                logger.exception("Failed to add missing columns %s: %s", missing, e)
    except Exception as e:
        logger.exception("Failed to ensure DB schema: %s", e)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def add_user_if_new(user_id: int, first_name: Optional[str] = None, username: Optional[str] = None) -> bool:
    """
    Insert a user if not exists.
    Returns True if inserted (new), False if already present or on error.
    """
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
                logger.info("New user added to DB: %s (%s / @%s)", user_id, first_name, username)
            return bool(inserted)
    except Exception as e:
        logger.exception("Failed to add user %s: %s", user_id, e)
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def user_exists(user_id: int) -> bool:
    """Return True if user_id is present in users table, otherwise False."""
    if not os.path.exists(DB_PATH):
        return False
    conn = _connect()
    try:
        cur = conn.execute("SELECT 1 FROM users WHERE user_id = ? LIMIT 1;", (int(user_id),))
        r = cur.fetchone()
        return bool(r)
    except Exception as e:
        logger.exception("Failed to check user_exists for %s: %s", user_id, e)
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def delete_user(user_id: int) -> bool:
    """Delete a user from DB. Returns True if a row was deleted."""
    if not os.path.exists(DB_PATH):
        return False
    conn = _connect()
    try:
        with conn:
            cur = conn.execute("DELETE FROM users WHERE user_id = ?;", (int(user_id),))
            return cur.rowcount > 0
    except Exception as e:
        logger.exception("Failed to delete user %s: %s", user_id, e)
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_all_users(as_rows: bool = False) -> List[Union[int, Tuple]]:
    """
    Return list of users.
    - as_rows=False -> [user_id, ...]
    - as_rows=True  -> [(user_id, first_name, username, added_at), ...]
    WARNING: this loads all results into memory; for large lists use get_all_users_in_chunks().
    This function is defensive: if added_at or other columns are missing it will adapt.
    """
    if not os.path.exists(DB_PATH):
        return []
    conn = _connect()
    try:
        cols = _table_columns(conn, "users")
        # decide ordering
        order_by = "added_at DESC" if "added_at" in cols else "user_id DESC"

        if as_rows:
            # pick columns in expected order, fall back to NULL if missing
            select_cols = []
            for c in ("user_id", "first_name", "username", "added_at"):
                if c in cols:
                    select_cols.append(c)
                else:
                    # create placeholder so returned tuple shape is stable
                    select_cols.append(f"NULL AS {c}")
            sql = "SELECT " + ", ".join(select_cols) + f" FROM users ORDER BY {order_by};"
            cur = conn.execute(sql)
            rows = cur.fetchall()
            return rows
        else:
            if "user_id" in cols:
                cur = conn.execute(f"SELECT user_id FROM users ORDER BY {order_by};")
                rows = cur.fetchall()
                return [int(r[0]) for r in rows]
            else:
                # fallback: return first column values
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
        logger.exception("Failed to fetch users: %s", e)
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_all_users_in_chunks(chunk_size: int = 1000) -> Generator[List[int], None, None]:
    """
    Generator yielding lists of user_id (int) in chunks.
    Useful for broadcasting to avoid loading whole table to memory at once.
    """
    if not os.path.exists(DB_PATH):
        return
        yield  # keeps generator type
    conn = _connect()
    try:
        cols = _table_columns(conn, "users")
        order_by = "added_at DESC" if "added_at" in cols else "user_id DESC"
        offset = 0
        while True:
            cur = conn.execute(
                f"SELECT user_id FROM users ORDER BY {order_by} LIMIT ? OFFSET ?;",
                (chunk_size, offset),
            )
            rows = cur.fetchall()
            if not rows:
                break
            yield [int(r[0]) for r in rows]
            offset += len(rows)
    except Exception as e:
        logger.exception("Failed to fetch users in chunks: %s", e)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_user_count() -> int:
    """Return total unique users in the DB (0 if missing or error)."""
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
        try:
            conn.close()
        except Exception:
            pass


def sample_users(limit: int = 10) -> List[Tuple]:
    """
    Return sample rows for admin debugging:
      [(user_id, first_name, username, added_at_human_readable), ...]
    Works even if first_name/username/added_at are missing.
    """
    if not os.path.exists(DB_PATH):
        return []
    conn = _connect()
    try:
        cols = _table_columns(conn, "users")
        # build select list depending on available columns
        select_cols = []
        out_cols = []
        if "user_id" in cols:
            select_cols.append("user_id")
            out_cols.append("user_id")
        if "first_name" in cols:
            select_cols.append("first_name")
            out_cols.append("first_name")
        if "username" in cols:
            select_cols.append("username")
            out_cols.append("username")
        if "added_at" in cols:
            select_cols.append("added_at")
            out_cols.append("added_at")
        if select_cols:
            sql = "SELECT " + ", ".join(select_cols) + " FROM users ORDER BY " + ("added_at" if "added_at" in cols else "user_id") + " DESC LIMIT ?;"
            cur = conn.execute(sql, (limit,))
            rows = cur.fetchall()
            # If added_at present and is integer, convert it to human-readable in returned tuples (if included)
            out = []
            for r in rows:
                # map to stable tuple of length equal to number of out_cols
                tup = list(r)
                # if added_at is present and it's the last element, convert it
                if "added_at" in out_cols:
                    idx = out_cols.index("added_at")
                    try:
                        val = tup[idx]
                        if val is not None:
                            tup[idx] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(val)))
                    except Exception:
                        pass
                out.append(tuple(tup))
            return out
        else:
            # fallback: select * and return raw rows (limited)
            cur = conn.execute("SELECT * FROM users LIMIT ?;", (limit,))
            rows = cur.fetchall()
            return rows
    except Exception as e:
        logger.exception("Failed to sample users: %s", e)
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def migrate_from_list(items: Iterable[Union[int, dict]]) -> int:
    """
    Convenience helper to import old lists of user ids into the DB.
    Accepts:
      - iterable of ints (user_id)
      - iterable of dicts like { "user_id": ..., "first_name": ..., "username": ... }
    Returns: number of users newly added.
    """
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


# ensure DB on import so features can rely on table being present
ensure_db()
