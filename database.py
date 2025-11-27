# database.py
import os
import sqlite3
import time
from typing import Dict, List, Optional

DB_PATH = os.getenv("DB_PATH", "data.db")


# ============================================================
# Initialize DB
# ============================================================

def initialize_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Users
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY
        )
    """)

    # Book request counters
    c.execute("""
        CREATE TABLE IF NOT EXISTS book_requests (
            book_code TEXT PRIMARY KEY,
            count INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Ratings
    c.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            user_id INTEGER,
            book_code TEXT,
            rating INTEGER,
            PRIMARY KEY (user_id, book_code)
        )
    """)

    # Countdowns (UPDATED: now includes message_id)
    c.execute("""
        CREATE TABLE IF NOT EXISTS countdowns (
            user_id INTEGER,
            book_code TEXT,
            end_timestamp INTEGER,
            message_id INTEGER,
            PRIMARY KEY (user_id, book_code)
        )
    """)

    # Tokens
    c.execute("""
        CREATE TABLE IF NOT EXISTS tokens (
            token TEXT PRIMARY KEY,
            user_id INTEGER,
            used INTEGER DEFAULT 0
        )
    """)

    # Bridges
    c.execute("""
        CREATE TABLE IF NOT EXISTS bridges (
            user_id INTEGER PRIMARY KEY,
            admin_id INTEGER,
            started_at INTEGER
        )
    """)

    conn.commit()
    conn.close()


# ============================================================
# Users
# ============================================================

def add_user_if_not_exists(user_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()


def get_all_users() -> List[int]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]


# ============================================================
# Book Requests
# ============================================================

def increment_book_request(book_code: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO book_requests (book_code, count)
        VALUES (?, 1)
        ON CONFLICT(book_code) DO UPDATE SET count = count + 1
    """, (book_code,))
    conn.commit()
    conn.close()


# ============================================================
# Countdowns (UPDATED)
# ============================================================

def save_countdown(user_id: int, book_code: str, end_timestamp: int, message_id: int) -> None:
    """
    Save or update the countdown timer.
    end_timestamp = unix timestamp when to delete message
    message_id = the Telegram message to delete
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO countdowns (user_id, book_code, end_timestamp, message_id)
        VALUES (?, ?, ?, ?)
    """, (user_id, book_code, end_timestamp, message_id))
    conn.commit()
    conn.close()


def get_all_countdowns() -> List[dict]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT user_id, book_code, end_timestamp, message_id
        FROM countdowns
    """)
    rows = c.fetchall()
    conn.close()

    return [
        {
            "user_id": r[0],
            "book_code": r[1],
            "end_timestamp": r[2],
            "message_id": r[3],
        }
        for r in rows
    ]


def delete_countdown(user_id: int, book_code: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "DELETE FROM countdowns WHERE user_id = ? AND book_code = ?",
        (user_id, book_code)
    )
    conn.commit();
    conn.close()


# ============================================================
# Background Countdown Helper (ADDED)
# ============================================================

def get_expired_countdowns(current_timestamp: int) -> List[dict]:
    """
    Returns all countdowns where end_timestamp <= now.
    Used by background worker to delete messages automatically.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT user_id, book_code, end_timestamp, message_id
        FROM countdowns
        WHERE end_timestamp <= ?
    """, (current_timestamp,))
    rows = c.fetchall()
    conn.close()

    return [
        {
            "user_id": r[0],
            "book_code": r[1],
            "end_timestamp": r[2],
            "message_id": r[3],
        }
        for r in rows
    ]


# ============================================================
# Ratings
# ============================================================

def save_rating(user_id: int, book_code: str, rating: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO ratings (user_id, book_code, rating)
        VALUES (?, ?, ?)
    """, (user_id, book_code, rating))
    conn.commit()
    conn.close()


def has_rated(user_id: int, book_code: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT 1 FROM ratings
        WHERE user_id = ? AND book_code = ?
    """, (user_id, book_code))
    ok = c.fetchone()
    conn.close()
    return ok is not None


# ============================================================
# Tokens
# ============================================================

def save_token(user_id: int, token: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM tokens WHERE user_id = ?", (user_id,))
    c.execute("""
        INSERT OR REPLACE INTO tokens (token, user_id, used)
        VALUES (?, ?, 0)
    """, (token, user_id))
    conn.commit()
    conn.close()


def get_token_owner(token: str) -> Optional[int]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM tokens WHERE token=?", (token,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def is_token_used(token: str) -> bool:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT used FROM tokens WHERE token=?", (token,))
    row = c.fetchone()
    conn.close()
    return bool(row and row[0] == 1)


def mark_token_used(token: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE tokens SET used = 1 WHERE token=?", (token,))
    conn.commit()
    conn.close()


# ============================================================
# Bridges
# ============================================================

def start_bridge(user_id: int, admin_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO bridges (user_id, admin_id, started_at)
        VALUES (?, ?, ?)
    """, (user_id, admin_id, int(time.time())))
    conn.commit()
    conn.close()


def get_bridge_admin(user_id: int) -> Optional[int]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT admin_id FROM bridges WHERE user_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def end_bridge(user_id: int) -> None:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM bridges WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

