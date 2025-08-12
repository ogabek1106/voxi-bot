#db_utils.py

import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = os.getenv("DB_PATH", "data.db")

# Ensure directory exists (e.g., /data)
db_dir = os.path.dirname(DB_PATH)
if db_dir:
    Path(db_dir).mkdir(parents=True, exist_ok=True)

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        yield c
        conn.commit()
    finally:
        conn.close()

# ----------- USERS -----------
def add_user(user_id: int):
    with get_db() as db:
        db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))

def get_total_users() -> int:
    with get_db() as db:
        db.execute("SELECT COUNT(*) FROM users")
        return db.fetchone()[0]

# ----------- BOOK REQUEST COUNTS -----------
def increment_book_count(book_code: str):
    with get_db() as db:
        db.execute("""
            INSERT INTO book_requests (book_code, count) VALUES (?, 1)
            ON CONFLICT(book_code) DO UPDATE SET count = count + 1
        """, (book_code,))

def get_book_stats() -> dict:
    with get_db() as db:
        db.execute("SELECT book_code, count FROM book_requests")
        rows = db.fetchall()
        return {code: count for code, count in rows}

# ----------- RATINGS -----------
def save_rating(user_id: int, book_code: str, rating: int):
    with get_db() as db:
        db.execute("""
            INSERT OR REPLACE INTO ratings (user_id, book_code, rating)
            VALUES (?, ?, ?)
        """, (user_id, book_code, rating))

def has_rated(user_id: int, book_code: str) -> bool:
    with get_db() as db:
        db.execute("SELECT 1 FROM ratings WHERE user_id = ? AND book_code = ?", (user_id, book_code))
        return db.fetchone() is not None

def get_rating_stats() -> dict:
    with get_db() as db:
        db.execute("SELECT book_code, rating FROM ratings")
        rows = db.fetchall()

    stats = {}
    for book_code, rating in rows:
        stats.setdefault(book_code, {str(i): 0 for i in range(1, 6)})
        stats[book_code][str(rating)] += 1
    return stats
