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

# ---------- TESTS TABLE ----------

def ensure_tests_table():
    """
    Ensure tests table exists AND is migration-safe.
    Adds missing columns without deleting data.
    """
    _ensure_db_dir()
    conn = None
    try:
        conn = _connect()

        # 1️⃣ Create table if it does not exist (new installs)
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tests (
                    test_id TEXT PRIMARY KEY
                );
                """
            )

        # 2️⃣ Check existing columns
        existing_cols = _table_columns(conn, "tests")

        # Required columns and their types
        required = {
            "test_id": "TEXT",
            "name": "TEXT",
            "level": "TEXT",
            "question_count": "INTEGER",
            "time_limit": "INTEGER",
            "created_at": "INTEGER",
        }

        # 3️⃣ Add missing columns safely (NO data deletion)
        for col, col_type in required.items():
            if col not in existing_cols:
                try:
                    with conn:
                        conn.execute(
                            f"ALTER TABLE tests ADD COLUMN {col} {col_type};"
                        )
                        logger.info("ensure_tests_table: added column %s", col)
                except Exception as e:
                    logger.warning(
                        "ensure_tests_table: failed to add column %s: %s",
                        col,
                        e,
                    )

    except Exception as e:
        logger.exception("ensure_tests_table failed: %s", e)
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

def create_test_meta(
    test_id: str,
    name: Optional[str],
    level: Optional[str],
    question_count: Optional[int],
    time_limit: Optional[int],
) -> bool:
    """
    Insert test metadata into DB.
    """
    ensure_tests_table()
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                INSERT INTO tests
                (test_id, name, level, question_count, time_limit, created_at)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    test_id,
                    name,
                    level,
                    question_count,
                    time_limit,
                    int(time.time()),
                ),
            )
        return True
    except Exception as e:
        logger.exception("create_test_meta failed for %s: %s", test_id, e)
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_all_tests() -> List[tuple]:
    """
    Return all tests ordered by newest first.
    """
    ensure_tests_table()
    conn = None
    try:
        conn = _connect()
        cur = conn.execute(
            """
            SELECT test_id, name, level, question_count, time_limit, created_at
            FROM tests
            ORDER BY created_at DESC;
            """
        )
        return cur.fetchall()
    except Exception as e:
        logger.exception("get_all_tests failed: %s", e)
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_test_meta(test_id: str) -> Optional[tuple]:
    ensure_tests_table()
    conn = None
    try:
        conn = _connect()
        cur = conn.execute(
            """
            SELECT test_id, name, level, question_count, time_limit, created_at
            FROM tests
            WHERE test_id = ?
            LIMIT 1;
            """,
            (test_id,),
        )
        return cur.fetchone()
    except Exception as e:
        logger.exception("get_test_meta failed for %s: %s", test_id, e)
        return None
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def delete_test(test_id: str) -> bool:
    ensure_tests_table()
    conn = None
    try:
        conn = _connect()
        with conn:
            cur = conn.execute("DELETE FROM tests WHERE test_id = ?;", (test_id,))
            return cur.rowcount > 0
    except Exception as e:
        logger.exception("delete_test failed for %s: %s", test_id, e)
        return False
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

# ---------- TEST DEFINITIONS (FOR /create_test ONLY) ----------

def ensure_test_defs_table():
    """
    Table for TEST DEFINITIONS (name, level, duration).
    This is NOT user attempts.
    Safe additive table.
    """
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS test_defs (
                    test_id TEXT PRIMARY KEY,
                    name TEXT,
                    level TEXT,
                    question_count INTEGER,
                    time_limit INTEGER,
                    created_at INTEGER
                );
                """
            )
    except Exception as e:
        logger.exception("ensure_test_defs_table failed: %s", e)
    finally:
        if conn:
            conn.close()


def save_test_definition(
    test_id: str,
    name: Optional[str],
    level: Optional[str],
    question_count: Optional[int],
    time_limit: Optional[int],
) -> bool:
    """
    Save test definition created via /create_test.
    """
    ensure_test_defs_table()
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                INSERT INTO test_defs
                (test_id, name, level, question_count, time_limit, created_at)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (
                    test_id,
                    name,
                    level,
                    question_count,
                    time_limit,
                    int(time.time()),
                ),
            )
        return True
    except Exception as e:
        logger.exception("save_test_definition failed for %s: %s", test_id, e)
        return False
    finally:
        if conn:
            conn.close()


def get_all_test_definitions():
    ensure_test_defs_table()
    conn = None
    try:
        conn = _connect()
        cur = conn.execute(
            """
            SELECT test_id, name, level, question_count, time_limit, created_at
            FROM test_defs
            ORDER BY created_at DESC;
            """
        )
        return cur.fetchall()
    except Exception as e:
        logger.exception("get_all_test_definitions failed: %s", e)
        return []
    finally:
        if conn:
            conn.close()


# ---------- TEST QUESTIONS (FOR create_test2.py) ----------

def ensure_test_questions_table():
    """
    Stores questions + answers for each test.
    One row = one question.
    """
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS test_questions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    test_id TEXT NOT NULL,
                    question_number INTEGER NOT NULL,
                    question_text TEXT NOT NULL,
                    a TEXT NOT NULL,
                    b TEXT NOT NULL,
                    c TEXT NOT NULL,
                    d TEXT NOT NULL,
                    correct_answer TEXT NOT NULL,
                    created_at INTEGER
                );
                """
            )
    except Exception as e:
        logger.exception("ensure_test_questions_table failed: %s", e)
    finally:
        if conn:
            conn.close()

def save_test_question(
    test_id: str,
    question_number: int,
    question_text: str,
    answers: dict,
    correct_answer: str,
) -> bool:
    """
    Save a single question for a test.
    """
    ensure_test_questions_table()
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                INSERT INTO test_questions
                (test_id, question_number, question_text, a, b, c, d, correct_answer, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    test_id,
                    question_number,
                    question_text,
                    answers["a"],
                    answers["b"],
                    answers["c"],
                    answers["d"],
                    correct_answer,
                    int(time.time()),
                ),
            )
        return True
    except Exception as e:
        logger.exception("save_test_question failed for %s q=%s: %s", test_id, question_number, e)
        return False
    finally:
        if conn:
            conn.close()

def get_test_definition(test_id: str):
    """
    Return test definition from test_defs.
    """
    ensure_test_defs_table()
    conn = None
    try:
        conn = _connect()
        cur = conn.execute(
            """
            SELECT test_id, name, level, question_count, time_limit, created_at
            FROM test_defs
            WHERE test_id = ?
            LIMIT 1;
            """,
            (test_id,),
        )
        return cur.fetchone()
    except Exception as e:
        logger.exception("get_test_definition failed for %s: %s", test_id, e)
        return None
    finally:
        if conn:
            conn.close()

# ---------- TEST ANSWERS (USER RESPONSES) ----------

def ensure_test_answers_table():
    """
    Stores user's selected answers for each test attempt.
    One row = one answered question.
    """
    conn = None
    try:
        conn = _connect()

        # 1️⃣ Create table if not exists (NEW installs)
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS test_answers (
                    token TEXT NOT NULL,
                    test_id TEXT,
                    question_number INTEGER NOT NULL,
                    selected_answer TEXT NOT NULL,
                    PRIMARY KEY (token, question_number)
                );
                """
            )

        # 2️⃣ Add test_id column if missing (OLD installs)
        cols = _table_columns(conn, "test_answers")
        if "test_id" not in cols:
            try:
                with conn:
                    conn.execute("ALTER TABLE test_answers ADD COLUMN test_id TEXT;")
                logger.info("ensure_test_answers_table: added column test_id")
            except Exception as e:
                logger.warning("ensure_test_answers_table: failed to add test_id: %s", e)

    except Exception as e:
        logger.exception("ensure_test_answers_table failed: %s", e)
    finally:
        if conn:
            conn.close()


def save_test_answer(
    token: str,
    test_id: str,
    question_number: int,
    selected_answer: str
) -> bool:
    ensure_test_answers_table()
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO test_answers
                (token, test_id, question_number, selected_answer)
                VALUES (?, ?, ?, ?);
                """,
                (token, test_id, int(question_number), selected_answer),
            )
        return True
     
    except Exception as e:
        logger.exception(
            "save_test_answer failed (token=%s q=%s): %s",
            token, question_number, e
        )
        return False
    finally:
        if conn:
            conn.close()


def get_test_answers(token: str):
    ensure_test_answers_table()
    conn = None
    try:
        conn = _connect()
        cur = conn.execute(
            """
            SELECT test_id, question_number, selected_answer
            FROM test_answers
            WHERE token = ?;
            """,
            (token,),
        )
        return cur.fetchall()

    except Exception as e:
        logger.exception("get_test_answers failed for token %s: %s", token, e)
        return []
    finally:
        if conn:
            conn.close()


# ---------- TEST SCORES (FINAL RESULTS) ----------

def ensure_test_scores_table():
    """
    Stores final calculated score per test attempt.
    One row = one finished test (token-based).
    """
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS test_scores (
                    token TEXT PRIMARY KEY,
                    test_id TEXT NOT NULL,
                    user_id INTEGER,
                    total_questions INTEGER NOT NULL,
                    correct_answers INTEGER NOT NULL,
                    score REAL NOT NULL,
                    max_score INTEGER NOT NULL,
                    finished_at INTEGER
                );
                """
            )
                 # ---- ADD MISSING COLUMNS (SAFE MIGRATION) ----
        cols = _table_columns(conn, "test_scores")

        if "time_left" not in cols:
            try:
                with conn:
                    conn.execute("ALTER TABLE test_scores ADD COLUMN time_left INTEGER;")
                logger.info("ensure_test_scores_table: added column time_left")
            except Exception as e:
                logger.warning("ensure_test_scores_table: failed to add time_left: %s", e)

        if "auto_finished" not in cols:
            try:
                with conn:
                    conn.execute("ALTER TABLE test_scores ADD COLUMN auto_finished INTEGER;")
                logger.info("ensure_test_scores_table: added column auto_finished")
            except Exception as e:
                logger.warning("ensure_test_scores_table: failed to add auto_finished: %s", e)

        
    except Exception as e:
        logger.exception("ensure_test_scores_table failed: %s", e)
    finally:
        if conn:
            conn.close()

def save_test_score(
    token: str,
    test_id: str,
    user_id: int,
    total_questions: int,
    correct_answers: int,
    score: float,
    max_score: int = 100,
    time_left: Optional[int] = None,
    auto_finished: Optional[bool] = None,
) -> bool:
    ensure_test_scores_table()
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO test_scores
                (
                    token,
                    test_id,
                    user_id,
                    total_questions,
                    correct_answers,
                    score,
                    max_score,
                    finished_at,
                    time_left,
                    auto_finished
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,

                (
                   token,
                   test_id,
                   user_id,
                   total_questions,
                   correct_answers,
                   score,
                   max_score,
                   int(time.time()),
                   time_left,
                   int(auto_finished) if auto_finished is not None else None,
                   ),
            )
        return True
    except Exception as e:
        logger.exception("save_test_score failed for token %s: %s", token, e)
        return False
    finally:
        if conn:
            conn.close()

def get_test_score(token: str):
    ensure_test_scores_table()
    conn = None
    try:
        conn = _connect()
        cur = conn.execute(
            """
            SELECT
                token,
                test_id,
                user_id,
                total_questions,
                correct_answers,
                score,
                max_score,
                finished_at,
                time_left,
                auto_finished
            FROM test_scores
            WHERE token = ?
            LIMIT 1;
            """,
            (token,),
        )
        return cur.fetchone()
    except Exception as e:
        logger.exception("get_test_score failed for token %s: %s", token, e)
        return None
    finally:
        if conn:
            conn.close()


# ---------- ACTIVE TEST (PUBLISHED) ----------

def ensure_active_test_table():
    """
    Stores ONLY ONE active (published) test.
    If table has 0 rows -> no active test.
    """
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS active_test (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    test_id TEXT NOT NULL,
                    name TEXT,
                    level TEXT,
                    question_count INTEGER,
                    time_limit INTEGER,
                    published_at INTEGER
                );
                """
            )
    except Exception as e:
        logger.exception("ensure_active_test_table failed: %s", e)
    finally:
        if conn:
            conn.close()


def has_active_test() -> bool:
    ensure_active_test_table()
    conn = None
    try:
        conn = _connect()
        cur = conn.execute("SELECT 1 FROM active_test LIMIT 1;")
        return cur.fetchone() is not None
    except Exception as e:
        logger.exception("has_active_test failed: %s", e)
        return False
    finally:
        if conn:
            conn.close()


def set_active_test(
    test_id: str,
    name: Optional[str],
    level: Optional[str],
    question_count: Optional[int],
    time_limit: Optional[int],
) -> bool:
    """
    Publish a test.
    Fails if an active test already exists.
    """
    ensure_active_test_table()
    conn = None
    try:
        conn = _connect()
        with conn:
            cur = conn.execute("SELECT 1 FROM active_test LIMIT 1;")
            if cur.fetchone():
                return False

            conn.execute(
                """
                INSERT INTO active_test
                (id, test_id, name, level, question_count, time_limit, published_at)
                VALUES (1, ?, ?, ?, ?, ?, ?);
                """,
                (
                    test_id,
                    name,
                    level,
                    question_count,
                    time_limit,
                    int(time.time()),
                ),
            )
        return True
    except Exception as e:
        logger.exception("set_active_test failed for %s: %s", test_id, e)
        return False
    finally:
        if conn:
            conn.close()


def clear_active_test() -> bool:
    """
    Unpublish the current test.
    """
    ensure_active_test_table()
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute("DELETE FROM active_test;")
        return True
    except Exception as e:
        logger.exception("clear_active_test failed: %s", e)
        return False
    finally:
        if conn:
            conn.close()

def get_active_test():
    """
    Return the currently active (published) test or None.
    """
    ensure_active_test_table()
    conn = None
    try:
        conn = _connect()
        cur = conn.execute(
            """
            SELECT test_id, name, level, question_count, time_limit, published_at
            FROM active_test
            LIMIT 1;
            """
        )
        return cur.fetchone()
    except Exception as e:
        logger.exception("get_active_test failed: %s", e)
        return None
    finally:
        if conn:
            conn.close()

# ---------- AI CHECKER STATE ----------

def ensure_checker_state_table():
    """
    Stores current AI checking mode per user.
    One row = one active checker session.
    """
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS checker_state (
                    user_id INTEGER PRIMARY KEY,
                    mode TEXT NOT NULL,
                    started_at INTEGER
                );
                """
            )
    except Exception as e:
        logger.exception("ensure_checker_state_table failed: %s", e)
    finally:
        if conn:
            conn.close()

def set_checker_mode(user_id: int, mode: str) -> bool:
    """
    Enable AI checker mode for a user.
    """
    ensure_checker_state_table()
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO checker_state
                (user_id, mode, started_at)
                VALUES (?, ?, ?);
                """,
                (int(user_id), mode, int(time.time())),
            )
        return True
    except Exception as e:
        logger.exception("set_checker_mode failed for %s: %s", user_id, e)
        return False
    finally:
        if conn:
            conn.close()

def get_checker_mode(user_id: int) -> Optional[str]:
    """
    Return current checker mode for user or None.
    """
    ensure_checker_state_table()
    conn = None
    try:
        conn = _connect()
        cur = conn.execute(
            """
            SELECT mode
            FROM checker_state
            WHERE user_id = ?
            LIMIT 1;
            """,
            (int(user_id),),
        )
        row = cur.fetchone()
        return row[0] if row else None
    except Exception as e:
        logger.exception("get_checker_mode failed for %s: %s", user_id, e)
        return None
    finally:
        if conn:
            conn.close()

def clear_checker_mode(user_id: int) -> bool:
    """
    Disable AI checker mode for a user.
    """
    ensure_checker_state_table()
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                "DELETE FROM checker_state WHERE user_id = ?;",
                (int(user_id),),
            )
        return True
    except Exception as e:
        logger.exception("clear_checker_mode failed for %s: %s", user_id, e)
        return False
    finally:
        if conn:
            conn.close()


# ---------- COMMAND USAGE STATS ----------

def ensure_command_usage_table():
    """
    Stores every command usage with timestamp.
    One row = one command execution.
    """
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS command_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    command TEXT NOT NULL,
                    timestamp INTEGER NOT NULL
                );
                """
            )
    except Exception as e:
        logger.exception("ensure_command_usage_table failed: %s", e)
    finally:
        if conn:
            conn.close()

def log_command_use(command: str) -> None:
    """
    Log a command usage with current timestamp.
    """
    if not command:
        return

    ensure_command_usage_table()
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                INSERT INTO command_usage (command, timestamp)
                VALUES (?, ?);
                """,
                (command, int(time.time())),
            )
    except Exception as e:
        logger.exception("log_command_use failed for %s: %s", command, e)
    finally:
        if conn:
            conn.close()

def get_command_usage_stats():
    """
    Returns list of:
    (command, last_24h_count, total_count)
    Ordered by total_count DESC.
    """
    ensure_command_usage_table()

    now = int(time.time())
    last_24h_border = now - 86400  # 24 hours

    conn = None
    try:
        conn = _connect()
        cur = conn.execute(
            """
            SELECT
                command,
                SUM(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END) AS last_24h,
                COUNT(*) AS total
            FROM command_usage
            GROUP BY command
            ORDER BY total DESC;
            """,
            (last_24h_border,),
        )
        return cur.fetchall()
    except Exception as e:
        logger.exception("get_command_usage_stats failed: %s", e)
        return []
    finally:
        if conn:
            conn.close()

# ---------- BOOK REQUEST STATS ----------

def ensure_book_usage_table():
    """
    Stores every successful book request with timestamp.
    One row = one book request.
    """
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS book_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp INTEGER NOT NULL
                );
                """
            )
    except Exception as e:
        logger.exception("ensure_book_usage_table failed: %s", e)
    finally:
        if conn:
            conn.close()


def log_book_request(book_code: str = "") -> None:
    """
    Log a successful book request.
    book_code is ignored for now (future-proof).
    """
    ensure_book_usage_table()
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                INSERT INTO book_usage (timestamp)
                VALUES (?);
                """,
                (int(time.time()),),
            )
    except Exception as e:
        logger.exception("log_book_request failed: %s", e)
    finally:
        if conn:
            conn.close()


def get_total_book_request_stats():
    """
    Returns:
    (last_24h_count, total_count)
    """
    ensure_book_usage_table()

    now = int(time.time())
    last_24h_border = now - 86400

    conn = None
    try:
        conn = _connect()
        cur = conn.execute(
            """
            SELECT
                SUM(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END) AS last_24h,
                COUNT(*) AS total
            FROM book_usage;
            """,
            (last_24h_border,),
        )
        row = cur.fetchone()
        return int(row[0] or 0), int(row[1] or 0)
    except Exception as e:
        logger.exception("get_total_book_request_stats failed: %s", e)
        return 0, 0
    finally:
        if conn:
            conn.close()


# ---------- AI CHECKER USAGE (LIMITER) ----------

def ensure_ai_usage_table():
    """
    Stores every successful AI checker usage.
    One row = one completed check.
    """
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    feature TEXT NOT NULL,
                    used_at INTEGER NOT NULL
                );
                """
            )
    except Exception as e:
        logger.exception("ensure_ai_usage_table failed: %s", e)
    finally:
        if conn:
            conn.close()

def log_ai_usage(user_id: int, feature: str) -> None:
    """
    Log one successful AI checker usage.
    """
    if not feature:
        return

    ensure_ai_usage_table()
    conn = None
    try:
        conn = _connect()
        with conn:
            conn.execute(
                """
                INSERT INTO ai_usage (user_id, feature, used_at)
                VALUES (?, ?, ?);
                """,
                (int(user_id), feature, int(time.time())),
            )
    except Exception as e:
        logger.exception("log_ai_usage failed for %s (%s): %s", user_id, feature, e)
    finally:
        if conn:
            conn.close()

def count_ai_usage_since(user_id: int, feature: str, since_ts: int) -> int:
    """
    Count how many times user used a feature since timestamp.
    """
    ensure_ai_usage_table()
    conn = None
    try:
        conn = _connect()
        cur = conn.execute(
            """
            SELECT COUNT(*)
            FROM ai_usage
            WHERE user_id = ?
              AND feature = ?
              AND used_at >= ?;
            """,
            (int(user_id), feature, int(since_ts)),
        )
        row = cur.fetchone()
        return int(row[0] or 0)
    except Exception as e:
        logger.exception("count_ai_usage_since failed: %s", e)
        return 0
    finally:
        if conn:
            conn.close()

def get_last_ai_usage_time(user_id: int, feature: str) -> Optional[int]:
    """
    Return last usage timestamp for a feature or None.
    """
    ensure_ai_usage_table()
    conn = None
    try:
        conn = _connect()
        cur = conn.execute(
            """
            SELECT used_at
            FROM ai_usage
            WHERE user_id = ?
              AND feature = ?
            ORDER BY used_at DESC
            LIMIT 1;
            """,
            (int(user_id), feature),
        )
        row = cur.fetchone()
        return int(row[0]) if row else None
    except Exception as e:
        logger.exception("get_last_ai_usage_time failed: %s", e)
        return None
    finally:
        if conn:
            conn.close()

# ensure DB quickly on import (best-effort)
ensure_db()
# ensure tests table on import (best-effort)
ensure_tests_table()
ensure_test_defs_table()
ensure_test_questions_table()
ensure_test_answers_table()
ensure_test_scores_table()
ensure_active_test_table()
ensure_checker_state_table()
ensure_command_usage_table()
ensure_book_usage_table()
ensure_ai_usage_table()
