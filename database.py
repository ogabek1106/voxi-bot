#database.py

import os
import sqlite3
import time
from pathlib import Path

# ✅ Use persistent path if provided (Railway: /data/data.db)
DB_PATH = os.getenv("DB_PATH", "data.db")

# Make sure the directory exists (e.g., /data)
db_dir = os.path.dirname(DB_PATH)
if db_dir:
    Path(db_dir).mkdir(parents=True, exist_ok=True)

print(f"📦 Using SQLite at: {DB_PATH}")

def initialize_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS book_requests (
        book_code TEXT PRIMARY KEY,
        count INTEGER NOT NULL DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS ratings (
        user_id INTEGER,
        book_code TEXT,
        rating INTEGER,
        PRIMARY KEY (user_id, book_code)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS countdowns (
        user_id INTEGER,
        book_code TEXT,
        end_timestamp INTEGER,
        PRIMARY KEY (user_id, book_code)
    )""")
    conn.commit()
    conn.close()

# ----------- USERS -----------
def add_user_if_not_exists(user_id: int):
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

def get_all_users() -> list[int]:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    users = [row[0] for row in c.fetchall()]
    conn.close()
    return users

# ----------- BOOK REQUESTS -----------
def increment_book_request(book_code: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO book_requests (book_code, count) VALUES (?, 1)
        ON CONFLICT(book_code) DO UPDATE SET count = count + 1
    """, (book_code,))
    conn.commit()
    conn.close()

def get_book_stats() -> dict:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT book_code, count FROM book_requests")
    result = dict(c.fetchall())
    conn.close()
    return result

# ----------- RATINGS -----------
def save_rating(user_id: int, book_code: str, rating: int):
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
    c.execute("SELECT 1 FROM ratings WHERE user_id = ? AND book_code = ?", (user_id, book_code))
    result = c.fetchone()
    conn.close()
    return result is not None

def get_rating_stats() -> dict:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT book_code, rating, COUNT(*) FROM ratings GROUP BY book_code, rating")
    stats = {}
    for book_code, rating, count in c.fetchall():
        stats.setdefault(book_code, {i: 0 for i in range(1, 6)})
        stats[book_code][rating] = count
    conn.close()
    return stats

# ----------- COUNTDOWNS -----------
def save_countdown(user_id: int, book_code: str, seconds: int):
    end_time = int(time.time()) + seconds
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO countdowns (user_id, book_code, end_timestamp)
        VALUES (?, ?, ?)
    """, (user_id, book_code, end_time))
    conn.commit()
    conn.close()

def get_remaining_countdown(user_id: int, book_code: str) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT end_timestamp FROM countdowns
        WHERE user_id = ? AND book_code = ?
    """, (user_id, book_code))
    row = c.fetchone()
    conn.close()
    if not row:
        return 0
    remaining = row[0] - int(time.time())
    return max(0, remaining)
