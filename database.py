# database.py
import sqlite3
import time

DB_PATH = "voxi.db"


# --------- INITIALIZATION ---------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Users table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY
        )
    """)

    # Book request counters
    cur.execute("""
        CREATE TABLE IF NOT EXISTS book_requests (
            book_code TEXT PRIMARY KEY,
            count INTEGER DEFAULT 0
        )
    """)

    # Ratings: per book, rating bucket (1–5), count
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            book_code TEXT,
            rating INTEGER,
            count INTEGER DEFAULT 0,
            PRIMARY KEY (book_code, rating)
        )
    """)

    # Track which user already voted for which book
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rating_votes (
            user_id INTEGER,
            book_code TEXT,
            PRIMARY KEY (user_id, book_code)
        )
    """)

    # Countdown timers
    cur.execute("""
        CREATE TABLE IF NOT EXISTS countdowns (
            user_id INTEGER,
            book_code TEXT,
            end_timestamp INTEGER
        )
    """)

    conn.commit()
    conn.close()


# --------- USER TRACKING ---------
def add_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()


def get_user_count():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    result = cur.fetchone()[0]
    conn.close()
    return result


# --------- BOOK REQUEST COUNTERS ---------
def increment_book_request(book_code):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO book_requests (book_code, count)
        VALUES (?, 1)
        ON CONFLICT(book_code) DO UPDATE SET count = count + 1
    """, (book_code,))
    conn.commit()
    conn.close()


def get_book_request_count(book_code):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT count FROM book_requests WHERE book_code=?", (book_code,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0


# --------- RATINGS ---------
def add_rating(user_id, book_code, rating):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Prevent double vote
    cur.execute("SELECT 1 FROM rating_votes WHERE user_id=? AND book_code=?", (user_id, book_code))
    if cur.fetchone():
        conn.close()
        return False  # already rated

    # Add rating bucket
    cur.execute("""
        INSERT INTO ratings (book_code, rating, count)
        VALUES (?, ?, 1)
        ON CONFLICT(book_code, rating) DO UPDATE SET count = count + 1
    """, (book_code, rating))

    # Mark user as voted
    cur.execute("INSERT INTO rating_votes (user_id, book_code) VALUES (?, ?)", (user_id, book_code))

    conn.commit()
    conn.close()
    return True


def get_rating_stats(book_code):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT rating, count FROM ratings WHERE book_code=?", (book_code,))
    rows = cur.fetchall()
    conn.close()

    return {rating: count for rating, count in rows}


# --------- COUNTDOWNS ---------
def save_countdown(user_id, book_code, end_timestamp):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO countdowns (user_id, book_code, end_timestamp)
        VALUES (?, ?, ?)
    """, (user_id, book_code, end_timestamp))
    conn.commit()
    conn.close()


def get_countdown(user_id, book_code):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        SELECT end_timestamp FROM countdowns
        WHERE user_id=? AND book_code=?
    """, (user_id, book_code))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def remove_expired_countdowns():
    now = int(time.time())
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM countdowns WHERE end_timestamp < ?", (now,))
    conn.commit()
    conn.close()
