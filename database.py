# database.py
import os
import sqlite3
import time
from typing import Dict, List, Optional

DB_PATH = os.getenv("DB_PATH", "data.db")


def initialize_db():
    """Create all required tables if they don't exist."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS book_requests (
            book_code TEXT PRIMARY KEY,
            count INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    # Ratings stored per-user so we can prevent double-votes and compute stats
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS ratings (
            user_id INTEGER,
            book_code TEXT,
            rating INTEGER,
            PRIMARY KEY (user_id, book_code)
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS countdowns (
            user_id INTEGER,
            book_code TEXT,
            end_timestamp INTEGER,
            PRIMARY KEY (user_id, book_code)
        )
        """
    )

    # Tokens: token -> user, used flag
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS tokens (
            token TEXT PRIMARY KEY,
            user_id INTEGER,
            used INTEGER DEFAULT 0
        )
        """
    )

    # Bridges: link a user to an admin for support conversations
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS bridges (
            user_id INTEGER PRIMARY KEY,
            admin_id INTEGER,
            started_at INTEGER
        )
        """
    )

    conn.commit()
    conn.close()


# ---------- Users ----------
def add_user_if_not_exists(user_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()


def get_user_count() -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    count = c.fetchone()[0]
    conn.close()
    return count


def get_all_users() -> List[int]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows


# ---------- Book requests ----------
def increment_book_request(book_code: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO book_requests (book_code, count) VALUES (?, 1)
        ON CONFLICT(book_code) DO UPDATE SET count = count + 1
        """,
        (book_code,),
    )
    conn.commit()
    conn.close()


def get_book_stats() -> Dict[str, int]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT book_code, count FROM book_requests")
    rows = c.fetchall()
    conn.close()
    return {code: cnt for code, cnt in rows}


# ---------- Ratings ----------
def save_rating(user_id: int, book_code: str, rating: int) -> None:
    """
    Save or update a user's rating for a book.
    Replaces any previous rating from the same user for the same book.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        INSERT OR REPLACE INTO ratings (user_id, book_code, rating)
        VALUES (?, ?, ?)
        """,
        (user_id, book_code, rating),
    )
    conn.commit()
    conn.close()


def has_rated(user_id: int, book_code: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT 1 FROM ratings WHERE user_id = ? AND book_code = ?",
        (user_id, book_code),
    )
    ok = c.fetchone() is not None
    conn.close()
    return ok


def get_rating_stats() -> Dict[str, Dict[int, int]]:
    """
    Returns a dict:
      { book_code: {1: count, 2: count, 3: count, 4: count, 5: count}, ... }
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        SELECT book_code, rating, COUNT(*) as cnt
        FROM ratings
        GROUP BY book_code, rating
        """
    )
    rows = c.fetchall()
    conn.close()

    stats: Dict[str, Dict[int, int]] = {}
    for book_code, rating, cnt in rows:
        stats.setdefault(book_code, {i: 0 for i in range(1, 6)})
        stats[book_code][int(rating)] = cnt
    return stats


# ---------- Countdowns ----------
def save_countdown(user_id: int, book_code: str, seconds: int) -> None:
    end_time = int(time.time()) + int(seconds)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        INSERT OR REPLACE INTO countdowns (user_id, book_code, end_timestamp)
        VALUES (?, ?, ?)
        """,
        (user_id, book_code, end_time),
    )
    conn.commit()
    conn.close()


def get_remaining_countdown(user_id: int, book_code: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT end_timestamp FROM countdowns WHERE user_id = ? AND book_code = ?",
        (user_id, book_code),
    )
    row = c.fetchone()
    conn.close()
    if not row:
        return 0
    remaining = row[0] - int(time.time())
    return max(0, remaining)


def remove_countdown(user_id: int, book_code: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "DELETE FROM countdowns WHERE user_id = ? AND book_code = ?",
        (user_id, book_code),
    )
    conn.commit()
    conn.close()


# ---------- Tokens ----------
def save_token(user_id: int, token: str) -> None:
    """
    Ensure a user has at most one token row: delete previous tokens for that user,
    then insert the new token.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM tokens WHERE user_id = ?", (user_id,))
    c.execute("INSERT OR REPLACE INTO tokens (token, user_id, used) VALUES (?, ?, 0)", (token, user_id))
    conn.commit()
    conn.close()


def get_token_for_user(user_id: int) -> Optional[str]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT token FROM tokens WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def get_token_owner(token: str) -> Optional[int]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM tokens WHERE token = ?", (token,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def is_token_used(token: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT used FROM tokens WHERE token = ?", (token,))
    row = c.fetchone()
    conn.close()
    return bool(row and row[0] == 1)


def mark_token_used(token: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE tokens SET used = 1 WHERE token = ?", (token,))
    conn.commit()
    conn.close()


# ---------- Bridges ----------
def start_bridge(user_id: int, admin_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR REPLACE INTO bridges (user_id, admin_id, started_at) VALUES (?, ?, ?)",
        (user_id, admin_id, int(time.time())),
    )
    conn.commit()
    conn.close()


def get_bridge_admin(user_id: int) -> Optional[int]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT admin_id FROM bridges WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def end_bridge(user_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM bridges WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
