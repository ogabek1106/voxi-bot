# database.py

import sqlite3

def initialize_db():
    conn = sqlite3.connect("data.db")
    c = conn.cursor()

    # Create tables
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS book_requests (
        book_code TEXT PRIMARY KEY,
        count INTEGER NOT NULL DEFAULT 0
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS ratings (
        user_id INTEGER,
        book_code TEXT,
        rating INTEGER,
        PRIMARY KEY (user_id, book_code)
    )
    """)

    conn.commit()
    conn.close()

# 📌 Add user only if new
def add_user_if_not_exists(user_id: int):
    conn = sqlite3.connect("data.db")
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

# 📊 Get total users
def get_user_count() -> int:
    conn = sqlite3.connect("data.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    count = c.fetchone()[0]
    conn.close()
    return count

# 📈 Increment book request count (even duplicates)
def increment_book_request(book_code: str):
    conn = sqlite3.connect("data.db")
    c = conn.cursor()
    c.execute("INSERT INTO book_requests (book_code, count) VALUES (?, 1) ON CONFLICT(book_code) DO UPDATE SET count = count + 1", (book_code,))
    conn.commit()
    conn.close()

# 📊 Get all book request stats as {code: count}
def get_book_stats() -> dict:
    conn = sqlite3.connect("data.db")
    c = conn.cursor()
    c.execute("SELECT book_code, count FROM book_requests")
    result = dict(c.fetchall())
    conn.close()
    return result

# ⭐️ Save or update rating
def save_rating(user_id: int, book_code: str, rating: int):
    conn = sqlite3.connect("data.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO ratings (user_id, book_code, rating) VALUES (?, ?, ?)", (user_id, book_code, rating))
    conn.commit()
    conn.close()

# 🔍 Check if user already rated
def has_rated(user_id: int, book_code: str) -> bool:
    conn = sqlite3.connect("data.db")
    c = conn.cursor()
    c.execute("SELECT 1 FROM ratings WHERE user_id = ? AND book_code = ?", (user_id, book_code))
    result = c.fetchone()
    conn.close()
    return result is not None

# 📊 Get rating stats {code: {1: x, 2: y, ..., 5: z}}
def get_rating_stats() -> dict:
    conn = sqlite3.connect("data.db")
    c = conn.cursor()
    c.execute("SELECT book_code, rating, COUNT(*) FROM ratings GROUP BY book_code, rating")
    stats = {}
    for book_code, rating, count in c.fetchall():
        stats.setdefault(book_code, {i: 0 for i in range(1, 6)})
        stats[book_code][rating] = count
    conn.close()
    return stats
