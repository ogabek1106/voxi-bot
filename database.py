#database.py

import sqlite3

# Connect to the database
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
